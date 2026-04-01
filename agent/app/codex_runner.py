"""Codex CLI runner for SRE investigations.

Запускает `codex exec` как subprocess и захватывает результат.
Codex читает AGENTS.md с инструкциями (команды по типу алерта, формат отчёта).
stdout = финальное сообщение агента (чистый текст).
stderr = terminal UI (блоки user/codex/exec).
"""

import asyncio
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
    """Run Codex CLI and return the investigation report.

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
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")

    logger.info(
        "codex_exec_finished",
        investigation_id=investigation_id,
        exit_code=process.returncode,
        stdout_bytes=len(stdout_bytes),
        stderr_bytes=len(stderr_bytes),
        stdout_preview=stdout_text[:200] if stdout_text else "(empty)",
    )

    report = _extract_report(stdout_text, stderr_text)

    if report:
        tracer.span_llm_call(
            model=settings.codex_model,
            input_text=prompt[:300],
            output_text=report[:1000],
        )
        return report

    logger.warning("codex_no_report", investigation_id=investigation_id)
    return None


def _extract_report(stdout: str, stderr: str) -> str | None:
    """Extract report from Codex output.

    Returns stdout if non-empty (Codex puts final message there).
    Falls back to last text block from stderr terminal UI.

    Args:
        stdout: Codex stdout (final assistant message).
        stderr: Codex stderr (terminal UI).

    Returns:
        Report text or None.
    """
    if stdout:
        return stdout

    # Fallback: extract last "codex" message block from stderr
    if stderr:
        parts = stderr.split("\ncodex\n")
        if len(parts) > 1:
            tail = parts[-1]
            for stop in ("tokens used", "\nexec\n", "\nuser\n"):
                pos = tail.find(stop)
                if pos > 0:
                    tail = tail[:pos]
            if tail.strip():
                return tail.strip()

    return None


def _build_env() -> dict[str, str]:
    """Build env vars for Codex subprocess.

    Returns:
        Environment dict with OPENROUTER_API_KEY.
    """
    env = os.environ.copy()
    if "OPENROUTER_API_KEY" not in env:
        env["OPENROUTER_API_KEY"] = settings.gateway_api_key
    env.pop("OPENAI_BASE_URL", None)
    env.pop("OPENAI_API_KEY", None)
    return env
