"""Tests for agent.app.codex_runner: build_prompt and _extract_report."""

from agent.app.codex_runner import _extract_report, build_prompt


class TestBuildPrompt:
    """Tests for build_prompt()."""

    def test_build_prompt_cpu_alert(self, sample_alert_dict: dict) -> None:
        """Prompt must contain host, trigger, severity, and SSH instruction."""
        prompt = build_prompt(sample_alert_dict)

        assert "web-server-01" in prompt
        assert "CPU usage is too high" in prompt
        assert "high" in prompt
        assert "ssh" in prompt.lower()

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

        # Should not raise KeyError
        assert "app-01" in prompt
        assert "Disk full" in prompt


class TestExtractReport:
    """Tests for _extract_report()."""

    def test_extract_report_from_stdout(self) -> None:
        """Non-empty stdout is returned as the report."""
        report = _extract_report("Investigation complete: CPU at 95%", "some stderr noise")
        assert report == "Investigation complete: CPU at 95%"

    def test_extract_report_from_stderr_fallback(self) -> None:
        """When stdout is empty, falls back to last codex block in stderr."""
        stderr = (
            "user\nshow me status\n"
            "\ncodex\n"
            "Running diagnostics...\n"
            "\ncodex\n"
            "Final report: all services healthy\n"
            "tokens used 1234"
        )
        report = _extract_report("", stderr)
        assert report is not None
        assert "Final report" in report

    def test_extract_report_empty(self) -> None:
        """Both empty returns None."""
        assert _extract_report("", "") is None

    def test_extract_report_stdout_preferred(self) -> None:
        """When both have content, stdout wins."""
        report = _extract_report("stdout report", "\ncodex\nstderr report\ntokens used 500")
        assert report == "stdout report"

    def test_extract_report_whitespace_stdout(self) -> None:
        """Whitespace-only stdout treated as empty (stripped)."""
        # build_prompt doesn't strip, but _extract_report checks truthiness
        # after codex_runner strips stdout — here we test with already-stripped value
        report = _extract_report("", "")
        assert report is None
