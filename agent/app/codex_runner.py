"""Codex CLI runner for SRE investigations.

Запускает `codex exec --json` как subprocess и парсит JSON-события.
Каждое событие трейсится в Langfuse (command_execution → span, agent_message → generation).
Финальное agent_message = итоговый отчёт.
"""

import asyncio
import json
import os
import shutil

import structlog

from agent.app.config import settings
from agent.app.langfuse_tracer import InvestigationTracer

logger = structlog.get_logger()

CODEX_WORKDIR = "/opt/codex_workdir"


def build_prompt(alert: dict) -> str:
    """Build investigation prompt from Zabbix alert.

    Prompt содержит данные алерта. Инструкции по диагностике
    (команды, правила, формат отчёта) — в AGENTS.md.

    Args:
        alert: Zabbix alert data dict.

    Returns:
        Prompt string for Codex.
    """
    host = alert["host"]
    return (
        f"Получен алерт от Zabbix:\n"
        f"- Host: {host}\n"
        f"- Trigger: {alert['trigger']}\n"
        f"- Severity: {alert['severity']}\n"
        f"- Время: {alert['timestamp']}\n"
        f"- Описание: {alert.get('description', '')}\n\n"
        f"Подключение к серверу: `ssh {host} <command>`\n"
        f"Выполни 3-5 SSH-команд для диагностики, затем СРАЗУ напиши итоговый отчёт "
        f"по формату из AGENTS.md. НЕ выполняй больше команд после написания отчёта."
    )


async def run_codex(prompt: str, investigation_id: str, tracer: InvestigationTracer) -> str | None:
    """Run Codex CLI in JSON mode and return the investigation report.

    Parses JSON events from stdout, creates Langfuse spans for each
    command execution and agent message. Returns the last agent message
    as the investigation report.

    Args:
        prompt: Investigation prompt.
        investigation_id: Unique ID for logging.
        tracer: Langfuse tracer.

    Returns:
        Report text or None if Codex failed.
    """
    codex_path = shutil.which("codex")
    if not codex_path:
        logger.warning("codex_not_installed")
        return None

    # Ensure git repo (Codex requirement)
    if not os.path.exists(os.path.join(CODEX_WORKDIR, ".git")):
        await asyncio.create_subprocess_exec(
            "git", "init", cwd=CODEX_WORKDIR,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

    cmd = [
        "codex", "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--json",
        "--model", settings.codex_model,
        prompt,
    ]

    logger.info("codex_exec_starting", investigation_id=investigation_id, model=settings.codex_model)

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_build_env(),
        cwd=CODEX_WORKDIR,
    )

    try:
        async with asyncio.timeout(settings.investigation_timeout_seconds):
            stdout_bytes, stderr_bytes = await process.communicate()
    except TimeoutError:
        logger.error("codex_timeout", investigation_id=investigation_id)
        process.kill()
        return None

    stdout_text = stdout_bytes.decode("utf-8", errors="replace").strip()

    logger.info(
        "codex_exec_finished",
        investigation_id=investigation_id,
        exit_code=process.returncode,
        stdout_bytes=len(stdout_bytes),
    )

    return _parse_json_events(stdout_text, tracer)


def _parse_json_events(stdout: str, tracer: InvestigationTracer) -> str | None:
    """Parse Codex --json events and create Langfuse spans.

    Extracts the last agent_message as the report. Creates spans
    for command_execution events and generations for agent_messages.

    Args:
        stdout: Raw stdout with one JSON object per line.
        tracer: Langfuse tracer for span creation.

    Returns:
        Report text (last agent message) or None.
    """
    last_message: str | None = None
    total_input_tokens = 0
    total_output_tokens = 0

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_type = event.get("type", "")
        item = event.get("item", {})

        if event_type == "item.completed":
            item_type = item.get("type", "")

            if item_type == "agent_message":
                text = item.get("text", "")
                if text:
                    last_message = text
                    tracer.span_llm_call(
                        model=settings.codex_model,
                        input_text="",
                        output_text=text[:2000],
                    )

            elif item_type == "command_execution":
                tracer.span_shell_command(
                    command=item.get("command", "")[:500],
                    exit_code=item.get("exit_code", -1),
                    stdout=item.get("aggregated_output", "")[:4000],
                )

        elif event_type == "turn.completed":
            usage = event.get("usage", {})
            total_input_tokens += usage.get("input_tokens", 0)
            total_output_tokens += usage.get("output_tokens", 0)

    if total_input_tokens or total_output_tokens:
        logger.info(
            "codex_tokens",
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
        )

    return last_message


def _build_env() -> dict[str, str]:
    """Build env vars for Codex subprocess.

    Codex reads LITELLM_API_KEY from env (configured in config.toml env_key).
    Routes through LiteLLM Gateway for failover, metrics, and guardrails.

    Returns:
        Environment dict with LITELLM_API_KEY.
    """
    env = os.environ.copy()
    env["LITELLM_API_KEY"] = settings.gateway_api_key
    env.pop("OPENAI_BASE_URL", None)
    env.pop("OPENAI_API_KEY", None)
    return env
