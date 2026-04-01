"""Tests for agent.app.codex_runner: build_prompt and _parse_json_events."""

from unittest.mock import MagicMock

from agent.app.codex_runner import _parse_json_events, build_prompt


class TestBuildPrompt:
    """Tests for build_prompt()."""

    def test_build_prompt_cpu_alert(self, sample_alert_dict: dict) -> None:
        """Prompt must contain host, trigger, severity, and SSH instruction."""
        prompt = build_prompt(sample_alert_dict)

        assert "web-server-01" in prompt
        assert "CPU usage is too high" in prompt
        assert "high" in prompt
        assert "ssh web-server-01" in prompt

    def test_build_prompt_memory_alert(self) -> None:
        """Prompt for memory-related alert contains all required fields."""
        alert = {
            "alert_id": "m-001",
            "host": "db-node-03",
            "trigger": "Memory usage critical",
            "severity": "disaster",
            "timestamp": "2025-06-01T14:00:00Z",
            "description": "OOM killer invoked",
        }
        prompt = build_prompt(alert)

        assert "db-node-03" in prompt
        assert "Memory usage critical" in prompt
        assert "disaster" in prompt
        assert "OOM killer invoked" in prompt
        assert "ssh db-node-03" in prompt

    def test_build_prompt_missing_description(self) -> None:
        """When description key is absent, prompt defaults to empty string."""
        alert = {
            "alert_id": "x-001",
            "host": "app-01",
            "trigger": "Disk full",
            "severity": "warning",
            "timestamp": "2025-06-01T15:00:00Z",
        }
        prompt = build_prompt(alert)

        assert "app-01" in prompt
        assert "Disk full" in prompt


class TestParseJsonEvents:
    """Tests for _parse_json_events()."""

    def _make_tracer(self) -> MagicMock:
        """Create a mock tracer."""
        tracer = MagicMock()
        tracer.span_llm_call = MagicMock()
        tracer.span_shell_command = MagicMock()
        return tracer

    def test_parse_agent_message(self) -> None:
        """Last agent_message is returned as report."""
        tracer = self._make_tracer()
        stdout = '{"type":"item.completed","item":{"type":"agent_message","text":"## Report here"}}\n'

        report = _parse_json_events(stdout, tracer)

        assert report == "## Report here"
        tracer.span_llm_call.assert_called_once()

    def test_parse_command_execution(self) -> None:
        """command_execution creates shell_command span."""
        tracer = self._make_tracer()
        stdout = (
            '{"type":"item.completed","item":{"type":"command_execution",'
            '"command":"ssh playground uptime","aggregated_output":"up 2h","exit_code":0}}\n'
            '{"type":"item.completed","item":{"type":"agent_message","text":"Done"}}\n'
        )

        report = _parse_json_events(stdout, tracer)

        assert report == "Done"
        tracer.span_shell_command.assert_called_once_with(
            command="ssh playground uptime",
            exit_code=0,
            stdout="up 2h",
        )

    def test_parse_multiple_messages_returns_last(self) -> None:
        """When multiple agent_messages, returns the last one (report)."""
        tracer = self._make_tracer()
        stdout = (
            '{"type":"item.completed","item":{"type":"agent_message","text":"Running diagnostics..."}}\n'
            '{"type":"item.completed","item":{"type":"agent_message","text":"## Final Report"}}\n'
        )

        report = _parse_json_events(stdout, tracer)

        assert report == "## Final Report"
        assert tracer.span_llm_call.call_count == 2

    def test_parse_turn_completed_tokens(self) -> None:
        """turn.completed event extracts token usage."""
        tracer = self._make_tracer()
        stdout = (
            '{"type":"item.completed","item":{"type":"agent_message","text":"ok"}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":1000,"output_tokens":200}}\n'
        )

        report = _parse_json_events(stdout, tracer)

        assert report == "ok"

    def test_parse_empty_stdout(self) -> None:
        """Empty stdout returns None."""
        tracer = self._make_tracer()
        assert _parse_json_events("", tracer) is None

    def test_parse_invalid_json_lines_skipped(self) -> None:
        """Non-JSON lines are silently skipped."""
        tracer = self._make_tracer()
        stdout = (
            "not json\n"
            '{"type":"item.completed","item":{"type":"agent_message","text":"report"}}\n'
            "another garbage\n"
        )

        report = _parse_json_events(stdout, tracer)

        assert report == "report"
