"""MCP Tool: telegram_send — отправка отчёта в Telegram."""

import httpx
import structlog

from agent.app.config import settings

logger = structlog.get_logger()

TELEGRAM_API = "https://api.telegram.org"
MAX_RETRIES = 3


async def send_report(message: str) -> str:
    """Send incident report to Telegram chat.

    Sends a Markdown-formatted message to the configured Telegram chat.
    Retries up to MAX_RETRIES times on failure.

    Args:
        message: Report text in Markdown format.

    Returns:
        Status string indicating success or failure.
    """
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.warning("telegram_not_configured")
        return "Telegram not configured — report logged only"

    url = f"{TELEGRAM_API}/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": message[:4096],  # Telegram limit
        "parse_mode": "Markdown",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Try with Markdown first
        resp = await _send(client, url, payload)
        if resp and resp.status_code == 200:
            logger.info("telegram_sent", chat_id=settings.telegram_chat_id)
            return "Report sent to Telegram"

        # Fallback: send as plain text (LLM output may break Markdown parsing)
        payload.pop("parse_mode", None)
        resp = await _send(client, url, payload)
        if resp and resp.status_code == 200:
            logger.info("telegram_sent", chat_id=settings.telegram_chat_id, mode="plain")
            return "Report sent to Telegram (plain text)"

        last_error = f"HTTP {resp.status_code}: {resp.text[:200]}" if resp else "connection error"
        logger.error("telegram_send_exhausted", last_error=last_error)
        return f"Failed to send to Telegram: {last_error}"


async def _send(client: httpx.AsyncClient, url: str, payload: dict) -> httpx.Response | None:
    """Send a single Telegram API request with retries.

    Args:
        client: HTTP client.
        url: Telegram API URL.
        payload: Request payload.

    Returns:
        Response or None on connection error.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                return resp
            # 400 = parse error, don't retry — caller will try plain text
            if resp.status_code == 400:
                return resp
            logger.warning("telegram_send_failed", attempt=attempt, status=resp.status_code)
        except httpx.HTTPError as exc:
            logger.warning("telegram_send_error", attempt=attempt, error=str(exc))
    return None
