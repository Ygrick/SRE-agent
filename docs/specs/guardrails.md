# Спецификация: Guardrails (Custom для LiteLLM)

## Назначение

Кастомные guardrails, подключаемые к LiteLLM Proxy через `CustomGuardrail` base class. Защита от prompt injection и утечки секретов.

**Почему кастомные, а не enterprise:**
- `SecretDetection` в LiteLLM — enterprise-only (платная лицензия)
- Prompt injection через Lakera — зависимость от внешнего API
- Свои regex-правила: бесплатно, работают offline, полный контроль

## Архитектура

Guardrails выполняются как `pre_call` хуки в LiteLLM pipeline:

```
Request → LiteLLM Auth → Guardrails[PromptInjection → SecretLeak] → Router → Provider
```

Регистрация в `config.yaml`:
```yaml
general_settings:
  guardrails:
    - guardrail_name: "sre-prompt-injection"
      litellm_params:
        guardrail: "custom_guardrail.PromptInjectionGuardrail"
        mode: "pre_call"
    - guardrail_name: "sre-secret-leak"
      litellm_params:
        guardrail: "custom_guardrail.SecretLeakGuardrail"
        mode: "pre_call"
```

## Реализация

### Base class (LiteLLM API)

```python
from litellm.integrations.custom_guardrail import CustomGuardrail
from litellm.proxy._types import UserAPIKeyAuth
from litellm.types.guardrails import GuardrailEventHooks

class SREGuardrail(CustomGuardrail):
    async def async_pre_call_hook(
        self,
        user_api_key_dict: UserAPIKeyAuth,
        cache: DualCache,
        data: dict,
        call_type: str,
    ) -> None:
        """Вызывается перед отправкой запроса к LLM. Raise HTTPException для блокировки."""
        ...
```

### 1. Prompt Injection Detector

```python
INJECTION_PATTERNS = [
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
```

Проверяются все `content` полей `messages` в запросе. При срабатывании → `HTTPException(422)`.

### 2. Secret Leak Detector

```python
SECRET_PATTERNS = [
    (r"sk-[a-zA-Z0-9]{20,}", "openai_api_key"),
    (r"key-[a-zA-Z0-9]{20,}", "generic_api_key"),
    (r"AKIA[0-9A-Z]{16}", "aws_access_key"),
    (r"ghp_[a-zA-Z0-9]{36}", "github_token"),
    (r"gho_[a-zA-Z0-9]{36}", "github_oauth_token"),
    (r"xoxb-[0-9]{10,}", "slack_bot_token"),
    (r"://[^:]+:([^@]+)@", "password_in_url"),
    (r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----", "private_key"),
    (r"-----BEGIN\s+EC\s+PRIVATE\s+KEY-----", "ec_private_key"),
    (r"(?i)(password|passwd|pwd|secret|token)\s*[=:]\s*['\"]?[^\s'\"]{8,}", "generic_secret"),
]
```

При срабатывании: секрет НЕ логируется (только тип и позиция).

## Размещение кода

```
gateway/
├── custom_guardrail.py          # PromptInjectionGuardrail + SecretLeakGuardrail
└── litellm_config.yaml          # config с guardrails registration
```

Файл `custom_guardrail.py` монтируется в контейнер LiteLLM.

## Расширяемость

Новые guardrails добавляются как классы, наследующие `CustomGuardrail`, и регистрируются в `config.yaml`. Доступные хуки:
- `async_pre_call_hook` — до отправки к LLM (наш основной)
- `async_moderation_hook` — асинхронная модерация (не блокирует ответ)
- `async_post_call_success_hook` — после ответа (проверка output)
