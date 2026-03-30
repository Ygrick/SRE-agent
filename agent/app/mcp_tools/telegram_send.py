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

    last_error = ""
    async with httpx.AsyncClient(timeout=10.0) as client:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    logger.info("telegram_sent", chat_id=settings.telegram_chat_id)
                    return "Report sent to Telegram"
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                logger.warning(
                    "telegram_send_failed",
                    attempt=attempt,
                    status=resp.status_code,
                )
            except httpx.HTTPError as exc:
                last_error = str(exc)
                logger.warning("telegram_send_error", attempt=attempt, error=last_error)

    logger.error("telegram_send_exhausted", retries=MAX_RETRIES, last_error=last_error)
    return f"Failed to send to Telegram after {MAX_RETRIES} retries: {last_error}"
