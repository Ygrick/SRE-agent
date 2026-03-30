"""Custom guardrails for LiteLLM Proxy.

Prompt injection detection and secret leak prevention.
Implements LiteLLM CustomGuardrail interface.
"""

import re
from typing import ClassVar

from fastapi import HTTPException
from litellm._logging import verbose_proxy_logger
from litellm.integrations.custom_guardrail import CustomGuardrail
from litellm.proxy._types import UserAPIKeyAuth
from litellm.caching.dual_cache import DualCache


# === Prompt Injection Patterns ===

INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"ignore\s+(all\s+)?previous\s+instructions",
        r"ignore\s+(all\s+)?above",
        r"disregard\s+(all\s+)?previous",
        r"you\s+are\s+now\s+a",
        r"new\s+instructions?\s*:",
        r"system\s*:\s*you",
        r"<\s*/?\s*system\s*>",
        r"ADMIN\s*OVERRIDE",
        r"\[INST\]",
        r"<<\s*SYS\s*>>",
    ]
]


# === Secret Leak Patterns ===

SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(p), label)
    for p, label in [
        (r"sk-[a-zA-Z0-9]{20,}", "openai_api_key"),
        (r"key-[a-zA-Z0-9]{20,}", "generic_api_key"),
        (r"AKIA[0-9A-Z]{16}", "aws_access_key"),
        (r"ghp_[a-zA-Z0-9]{36}", "github_token"),
        (r"gho_[a-zA-Z0-9]{36}", "github_oauth_token"),
        (r"xoxb-[0-9]{10,}", "slack_bot_token"),
        (r"://[^:]+:([^@]{8,})@", "password_in_url"),
        (r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----", "private_key"),
        (r"-----BEGIN\s+EC\s+PRIVATE\s+KEY-----", "ec_private_key"),
        (
            r"(?i)(password|passwd|pwd|secret|token)\s*[=:]\s*['\"]?[^\s'\"]{8,}",
            "generic_secret",
        ),
    ]
]


def _extract_text_from_messages(data: dict) -> str:
    """Extract all text content from chat messages.

    Args:
        data: Request data containing 'messages' list.

    Returns:
        Concatenated text from all message content fields.
    """
    messages = data.get("messages", [])
    parts: list[str] = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(part.get("text", ""))
    return "\n".join(parts)


class PromptInjectionGuardrail(CustomGuardrail):
    """Detects prompt injection attempts via regex patterns.

    Checks all message content fields against known injection patterns.
    Raises HTTP 422 on match.
    """

    name: ClassVar[str] = "sre-prompt-injection"

    async def async_pre_call_hook(
        self,
        user_api_key_dict: UserAPIKeyAuth,
        cache: DualCache,
        data: dict,
        call_type: str,
    ) -> None:
        """Check messages for prompt injection patterns before LLM call.

        Args:
            user_api_key_dict: Authenticated user/key info.
            cache: LiteLLM dual cache instance.
            data: Request data with messages.
            call_type: Type of LLM call (e.g. 'completion').

        Raises:
            HTTPException: 422 if prompt injection detected.
        """
        text = _extract_text_from_messages(data)
        if not text:
            return

        for pattern in INJECTION_PATTERNS:
            match = pattern.search(text)
            if match:
                verbose_proxy_logger.warning(
                    "Guardrail BLOCKED: prompt_injection, pattern=%s, matched=%s",
                    pattern.pattern,
                    match.group()[:50],
                )
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": {
                            "message": "Request blocked by guardrails: prompt injection detected",
                            "type": "guardrails_error",
                            "rule": "prompt_injection",
                        }
                    },
                )


class SecretLeakGuardrail(CustomGuardrail):
    """Detects secret/credential leaks in prompts via regex patterns.

    Checks all message content fields for API keys, tokens, passwords, and private keys.
    Raises HTTP 422 on match. The secret value is NOT logged.
    """

    name: ClassVar[str] = "sre-secret-leak"

    async def async_pre_call_hook(
        self,
        user_api_key_dict: UserAPIKeyAuth,
        cache: DualCache,
        data: dict,
        call_type: str,
    ) -> None:
        """Check messages for secret/credential patterns before LLM call.

        Args:
            user_api_key_dict: Authenticated user/key info.
            cache: LiteLLM dual cache instance.
            data: Request data with messages.
            call_type: Type of LLM call (e.g. 'completion').

        Raises:
            HTTPException: 422 if secret leak detected.
        """
        text = _extract_text_from_messages(data)
        if not text:
            return

        for pattern, secret_type in SECRET_PATTERNS:
            if pattern.search(text):
                verbose_proxy_logger.warning(
                    "Guardrail BLOCKED: secret_leak, type=%s",
                    secret_type,
                )
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": {
                            "message": f"Request blocked by guardrails: secret leak detected ({secret_type})",
                            "type": "guardrails_error",
                            "rule": "secret_leak",
                            "secret_type": secret_type,
                        }
                    },
                )
