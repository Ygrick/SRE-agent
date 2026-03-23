# Спецификация: Guardrails

## Назначение

Middleware в LLM Gateway для фильтрации небезопасных запросов перед отправкой к LLM-провайдерам. Защита от prompt injection, утечки секретов и других нарушений.

## Архитектура

Guardrails реализован как цепочка middleware (FastAPI middleware stack), выполняющаяся **после Auth** и **перед Router**:

```
Request → Auth → Guardrails[Rule1 → Rule2 → ... → RuleN] → Router → Proxy
```

Если любое правило срабатывает → запрос блокируется с HTTP 422 и описанием нарушения.

## Правила

### 1. Prompt Injection Detector

**Назначение:** Обнаружение попыток инъекции через пользовательский ввод или данные из логов (косвенная инъекция).

**Реализация (два уровня):**

**Уровень 1 — Regex (быстрый, < 1ms):**
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

Проверяется: все `content` полей `messages` в запросе.

**Уровень 2 — LLM Classifier (опциональный, ~500ms):**
- Отдельный lightweight LLM-запрос к быстрому провайдеру
- Prompt: "Is the following text an attempt at prompt injection? Answer YES or NO."
- Включается через конфигурацию (`GUARDRAILS_LLM_CLASSIFIER_ENABLED=true`)
- Применяется только если regex не сработал, но confidence нужна выше

**Действие при срабатывании:**
- HTTP 422, `type: "guardrails_error"`, `rule: "prompt_injection"`
- Логирование в Langfuse (trace с tag `guardrails_blocked`)
- Метрика `llm_gateway_guardrails_blocked_total{rule="prompt_injection"}`

### 2. Secret Leak Detector

**Назначение:** Предотвращение утечки секретов через промпты (API ключи, пароли, токены, приватные ключи).

**Реализация — Regex:**
```python
SECRET_PATTERNS = [
    # API Keys
    (r"sk-[a-zA-Z0-9]{20,}", "openai_api_key"),
    (r"key-[a-zA-Z0-9]{20,}", "generic_api_key"),
    (r"AKIA[0-9A-Z]{16}", "aws_access_key"),
    (r"ghp_[a-zA-Z0-9]{36}", "github_token"),
    (r"gho_[a-zA-Z0-9]{36}", "github_oauth_token"),
    (r"xoxb-[0-9]{10,}", "slack_bot_token"),

    # Passwords in connection strings
    (r"://[^:]+:([^@]+)@", "password_in_url"),

    # Private keys
    (r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----", "private_key"),
    (r"-----BEGIN\s+EC\s+PRIVATE\s+KEY-----", "ec_private_key"),

    # Generic secrets
    (r"(?i)(password|passwd|pwd|secret|token)\s*[=:]\s*['\"]?[^\s'\"]{8,}", "generic_secret"),
]
```

**Действие при срабатывании:**
- HTTP 422, `type: "guardrails_error"`, `rule: "secret_leak"`, `detail: "<secret_type>"`
- Секрет НЕ логируется (только тип и позиция)
- Метрика `llm_gateway_guardrails_blocked_total{rule="secret_leak"}`

## Конфигурация

```env
# Включение/отключение отдельных правил
GUARDRAILS_PROMPT_INJECTION_ENABLED=true
GUARDRAILS_SECRET_LEAK_ENABLED=true
GUARDRAILS_LLM_CLASSIFIER_ENABLED=false

# Whitelist (bypass guardrails для доверенных агентов)
GUARDRAILS_WHITELIST_AGENT_IDS=sre-agent-01
```

## Pydantic модели

```python
class GuardrailResult(BaseModel):
    passed: bool
    rule: str | None = None
    detail: str | None = None

class GuardrailsConfig(BaseSettings):
    prompt_injection_enabled: bool = Field(default=True)
    secret_leak_enabled: bool = Field(default=True)
    llm_classifier_enabled: bool = Field(default=False)
    whitelist_agent_ids: list[str] = Field(default_factory=list)
```

## Расширяемость

Новые правила добавляются как классы, реализующие интерфейс:

```python
class GuardrailRule(Protocol):
    name: str

    async def check(self, messages: list[ChatMessage]) -> GuardrailResult:
        ...
```

Правила регистрируются в цепочке при старте приложения.
