"""SRE Agent — FastAPI application.

Receives Zabbix alerts via webhook, runs investigations via Codex CLI
(or fallback LLM), and sends reports to Telegram.
"""

import asyncio
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
import structlog
from fastapi import BackgroundTasks, FastAPI, HTTPException

from agent.app.codex_runner import run_investigation
from agent.app.config import settings
from agent.app.langfuse_tracer import InvestigationTracer
from agent.app.mcp_tools.telegram_send import send_report
from agent.app.schemas import InvestigationResponse, ZabbixAlert

logger = structlog.get_logger()

# --- Deduplication ---

_processed_alerts: dict[str, float] = {}
DEDUP_TTL_SECONDS = 600  # 10 minutes


def _is_duplicate(alert_id: str) -> bool:
    """Check if alert was already processed within TTL.

    Args:
        alert_id: Alert identifier.

    Returns:
        True if duplicate.
    """
    now = time.time()
    # Cleanup expired entries
    expired = [k for k, t in _processed_alerts.items() if now - t > DEDUP_TTL_SECONDS]
    for k in expired:
        del _processed_alerts[k]

    if alert_id in _processed_alerts:
        return True
    _processed_alerts[alert_id] = now
    return False


# --- Metrics (simple counters, OTel can be added later) ---

_metrics = {
    "investigations_total": 0,
    "investigations_completed": 0,
    "investigations_failed": 0,
    "investigations_active": 0,
}


# --- A2A Registration ---


async def _register_in_registry() -> None:
    """Register this agent in A2A Agent Registry on startup."""
    if not settings.registry_url or not settings.registry_api_key:
        logger.warning("registry_not_configured")
        return

    card = {
        "id": "sre-agent-01",
        "name": "SRE Agent",
        "version": "0.1.0",
        "baseUrl": f"http://sre-agent:{settings.port}",
        "description": "L1 SRE incident diagnosis agent. Receives Zabbix alerts, "
        "runs diagnostics via SSH, searches Runbooks, sends reports to Telegram.",
        "skills": [
            {
                "id": "diagnose-incident",
                "name": "Diagnose Incident",
                "description": "Run shell diagnostics on playground via SSH",
            },
            {
                "id": "search-runbooks",
                "name": "Search Runbooks",
                "description": "Search vector DB for relevant incident runbooks",
            },
        ],
        "capabilities": {"streaming": False},
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Try create first
            resp = await client.post(
                f"{settings.registry_url}/agents",
                headers={"Authorization": f"Bearer {settings.registry_api_key}"},
                json=card,
            )
            if resp.status_code == 201:
                logger.info("a2a_registered", agent_id="sre-agent-01")
            elif resp.status_code == 409:
                # Already exists, update
                resp = await client.put(
                    f"{settings.registry_url}/agents/sre-agent-01",
                    headers={"Authorization": f"Bearer {settings.registry_api_key}"},
                    json=card,
                )
                logger.info("a2a_updated", agent_id="sre-agent-01", status=resp.status_code)
            else:
                logger.warning("a2a_registration_failed", status=resp.status_code, body=resp.text[:200])
    except Exception as exc:
        logger.warning("a2a_registration_error", error=str(exc))


# --- Lifespan ---


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan: register in A2A on startup.

    Args:
        app: FastAPI app instance.
    """
    logger.info("sre_agent_starting", port=settings.port, model=settings.codex_model)
    await _register_in_registry()
    yield
    logger.info("sre_agent_stopping")


app = FastAPI(title="SRE Agent", version="0.1.0", lifespan=lifespan)


# --- Background investigation ---


async def _investigate(alert: ZabbixAlert, investigation_id: str) -> None:
    """Run investigation in background.

    Args:
        alert: Zabbix alert data.
        investigation_id: Unique investigation ID.
    """
    _metrics["investigations_active"] += 1
    tracer = InvestigationTracer(
        alert_id=alert.alert_id,
        investigation_id=investigation_id,
        host=alert.host,
        severity=alert.severity,
    )

    try:
        report = await run_investigation(
            alert=alert.model_dump(),
            investigation_id=investigation_id,
            tracer=tracer,
        )

        # Send to Telegram
        telegram_report = (
            f"🔴 *SRE Agent Report*\n"
            f"Alert: `{alert.trigger}`\n"
            f"Host: `{alert.host}`\n"
            f"Severity: `{alert.severity}`\n\n"
            f"{report[:3500]}"
        )
        telegram_result = await send_report(telegram_report)
        tracer.span_tool_call("telegram_send", telegram_report[:200], telegram_result)

        tracer.finish(status="completed", output=report[:4000])
        _metrics["investigations_completed"] += 1

        logger.info(
            "investigation_completed",
            investigation_id=investigation_id,
            alert_id=alert.alert_id,
            report_length=len(report),
            telegram=telegram_result,
        )

    except Exception as exc:
        tracer.finish(status="failed", output=str(exc))
        _metrics["investigations_failed"] += 1
        logger.error(
            "investigation_failed",
            investigation_id=investigation_id,
            error=str(exc),
        )
    finally:
        _metrics["investigations_active"] -= 1


# --- Endpoints ---


@app.get("/health")
async def health() -> dict:
    """Health check endpoint.

    Returns:
        Status dict with metrics.
    """
    return {"status": "ok", "metrics": _metrics}


@app.post("/webhooks/zabbix", response_model=InvestigationResponse, status_code=202)
async def zabbix_webhook(
    alert: ZabbixAlert,
    background_tasks: BackgroundTasks,
) -> InvestigationResponse:
    """Receive a Zabbix alert and start async investigation.

    Args:
        alert: Incoming Zabbix alert payload.
        background_tasks: FastAPI background tasks.

    Returns:
        202 Accepted with investigation ID.

    Raises:
        HTTPException: 429 if too many active investigations.
    """
    # Deduplication
    if _is_duplicate(alert.alert_id):
        logger.info("alert_deduplicated", alert_id=alert.alert_id)
        return InvestigationResponse(
            status="skipped_duplicate",
            alert_id=alert.alert_id,
            investigation_id="",
        )

    # Concurrency limit
    if _metrics["investigations_active"] >= 5:
        raise HTTPException(429, "Too many active investigations (max 5)")

    investigation_id = str(uuid.uuid4())
    _metrics["investigations_total"] += 1

    logger.info(
        "alert_received",
        alert_id=alert.alert_id,
        host=alert.host,
        trigger=alert.trigger,
        severity=alert.severity,
        investigation_id=investigation_id,
    )

    background_tasks.add_task(_investigate, alert, investigation_id)

    return InvestigationResponse(
        status="accepted",
        alert_id=alert.alert_id,
        investigation_id=investigation_id,
    )


@app.get("/metrics")
async def metrics() -> dict:
    """Prometheus-compatible metrics endpoint (simple JSON for now).

    Returns:
        Metrics dict.
    """
    return _metrics
