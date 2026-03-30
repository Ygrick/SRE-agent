"""Langfuse tracing for SRE Agent (Level B).

Parses codex exec --json stdout events and creates Langfuse spans.
Level A (per LLM-request) is handled by LiteLLM natively.
"""

from datetime import datetime, timezone
from typing import Any

import structlog
from langfuse import Langfuse

from agent.app.config import settings

logger = structlog.get_logger()

_langfuse: Langfuse | None = None


def get_langfuse() -> Langfuse | None:
    """Get or create Langfuse client.

    Returns:
        Langfuse client or None if not configured.
    """
    global _langfuse
    if _langfuse is not None:
        return _langfuse

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        logger.warning("langfuse_not_configured")
        return None

    _langfuse = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )
    return _langfuse


class InvestigationTracer:
    """Traces an SRE investigation lifecycle in Langfuse.

    Creates a parent trace for the investigation and child spans
    for each LLM call, shell command, and tool call.

    Attributes:
        alert_id: Zabbix alert identifier.
        investigation_id: Unique investigation identifier.
        host: Affected host name.
        severity: Alert severity.
    """

    def __init__(
        self,
        alert_id: str,
        investigation_id: str,
        host: str,
        severity: str,
    ) -> None:
        """Initialize investigation tracer.

        Args:
            alert_id: Zabbix alert ID.
            investigation_id: Unique investigation ID.
            host: Affected host.
            severity: Alert severity.
        """
        self.alert_id = alert_id
        self.investigation_id = investigation_id
        self.host = host
        self.severity = severity
        self._langfuse = get_langfuse()
        self._trace = None

        if self._langfuse:
            self._trace = self._langfuse.trace(
                id=investigation_id,
                name="investigation",
                metadata={
                    "alert_id": alert_id,
                    "host": host,
                    "severity": severity,
                },
                tags=["sre-agent", severity],
            )

    def span_llm_call(
        self,
        model: str,
        input_text: str,
        output_text: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        duration_ms: float = 0,
    ) -> None:
        """Record an LLM call span.

        Args:
            model: Model name.
            input_text: Prompt text.
            output_text: Completion text.
            tokens_in: Input tokens.
            tokens_out: Output tokens.
            duration_ms: Duration in milliseconds.
        """
        if not self._trace:
            return
        self._trace.generation(
            name="llm_call",
            model=model,
            input=input_text,
            output=output_text,
            usage={"input": tokens_in, "output": tokens_out},
            metadata={"duration_ms": duration_ms},
        )

    def span_shell_command(
        self,
        command: str,
        exit_code: int,
        stdout: str,
        duration_ms: float = 0,
    ) -> None:
        """Record a shell command span.

        Args:
            command: Shell command executed.
            exit_code: Command exit code.
            stdout: Command output (truncated).
            duration_ms: Duration in milliseconds.
        """
        if not self._trace:
            return
        self._trace.span(
            name="shell_command",
            input={"command": command},
            output={"exit_code": exit_code, "stdout": stdout[:4000]},
            metadata={"duration_ms": duration_ms},
        )

    def span_tool_call(
        self,
        tool_name: str,
        input_data: Any,
        output_data: Any,
        duration_ms: float = 0,
    ) -> None:
        """Record a tool call span.

        Args:
            tool_name: MCP tool name (qdrant_search, telegram_send).
            input_data: Tool input.
            output_data: Tool output.
            duration_ms: Duration in milliseconds.
        """
        if not self._trace:
            return
        self._trace.span(
            name=f"tool:{tool_name}",
            input=input_data,
            output=output_data,
            metadata={"duration_ms": duration_ms},
        )

    def finish(self, status: str = "completed", output: str = "") -> None:
        """Finish the investigation trace.

        Args:
            status: Final status (completed, failed, timeout).
            output: Final report or error message.
        """
        if not self._trace:
            return
        self._trace.update(
            output=output[:4000],
            metadata={"status": status},
        )
        if self._langfuse:
            self._langfuse.flush()
        logger.info(
            "investigation_trace_finished",
            investigation_id=self.investigation_id,
            status=status,
        )

    def process_codex_event(self, event: dict) -> None:
        """Process a single codex --json event and create appropriate span.

        Args:
            event: Parsed JSON event from codex stdout.
        """
        event_type = event.get("type", "")

        if event_type == "message" and event.get("role") == "assistant":
            content = ""
            for item in event.get("content", []):
                if item.get("type") == "output_text":
                    content += item.get("text", "")
            if content:
                self.span_llm_call(
                    model=settings.codex_model,
                    input_text="",
                    output_text=content[:2000],
                )

        elif event_type == "function_call":
            self.span_tool_call(
                tool_name=event.get("name", "unknown"),
                input_data=event.get("arguments", {}),
                output_data=None,
            )

        elif event_type == "function_call_output":
            self.span_tool_call(
                tool_name=event.get("name", "unknown"),
                input_data=None,
                output_data=str(event.get("output", ""))[:2000],
            )

        elif event_type == "exec" or event_type == "shell":
            cmd = event.get("command", event.get("input", ""))
            self.span_shell_command(
                command=str(cmd)[:500],
                exit_code=event.get("exit_code", 0),
                stdout=str(event.get("output", event.get("stdout", "")))[:4000],
            )
