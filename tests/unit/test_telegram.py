"""Tests for agent.app.mcp_tools.telegram_send: send_report."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from agent.app.mcp_tools.telegram_send import send_report


@pytest.mark.asyncio
class TestSendReport:
    """Tests for send_report()."""

    async def test_send_report_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns warning when token or chat_id is empty."""
        monkeypatch.setenv("AGENT_TELEGRAM_BOT_TOKEN", "")
        monkeypatch.setenv("AGENT_TELEGRAM_CHAT_ID", "")

        # Reload settings to pick up env changes
        from agent.app import config
        from agent.app.config import AgentSettings

        patched_settings = AgentSettings()
        with patch.object(config, "settings", patched_settings):
            with patch("agent.app.mcp_tools.telegram_send.settings", patched_settings):
                result = await send_report("Test report")
                assert "not configured" in result.lower()

    async def test_send_report_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mocked httpx returns 200 on first attempt."""
        monkeypatch.setenv("AGENT_TELEGRAM_BOT_TOKEN", "fake-bot-token")
        monkeypatch.setenv("AGENT_TELEGRAM_CHAT_ID", "12345")

        from agent.app.config import AgentSettings

        patched_settings = AgentSettings()

        mock_response = httpx.Response(200, json={"ok": True})
        mock_post = AsyncMock(return_value=mock_response)

        with patch("agent.app.mcp_tools.telegram_send.settings", patched_settings):
            with patch("httpx.AsyncClient.post", mock_post):
                result = await send_report("Investigation report content")
                assert "sent" in result.lower()

    async def test_send_report_markdown_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When Markdown parse fails (400), falls back to plain text (200)."""
        monkeypatch.setenv("AGENT_TELEGRAM_BOT_TOKEN", "fake-bot-token")
        monkeypatch.setenv("AGENT_TELEGRAM_CHAT_ID", "12345")

        from agent.app.config import AgentSettings

        patched_settings = AgentSettings()

        call_count = 0

        async def mock_post(self_client: httpx.AsyncClient, url: str, **kwargs: object) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            payload = kwargs.get("json", {})
            if payload.get("parse_mode") == "Markdown":
                return httpx.Response(400, json={"ok": False, "description": "Bad Request: can't parse"})
            return httpx.Response(200, json={"ok": True})

        with patch("agent.app.mcp_tools.telegram_send.settings", patched_settings):
            with patch("httpx.AsyncClient.post", mock_post):
                result = await send_report("Report with *broken* markdown [")
                assert "plain text" in result.lower()
