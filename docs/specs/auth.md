# Спецификация: Auth (Авторизация)

## Назначение

Контроль доступа к LLM Gateway и Agent Registry. Используем встроенную систему авторизации LiteLLM для Gateway и собственную для Agent Registry.

## LiteLLM Auth (Gateway)

### Master Key

Административный ключ для управления LiteLLM (создание virtual keys, моделей, etc.):

```env
LITELLM_MASTER_KEY=sk-master-<generated>
```

Используется Platform Admin для конфигурации. Не выдаётся агентам.

### Virtual Keys (основной механизм для агентов)

LiteLLM хранит virtual keys в PostgreSQL со spend tracking и rate limiting.

**Создание ключа:**
```bash
curl -X POST http://litellm:4000/key/generate \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "key_alias": "sre-agent-01",
    "max_budget": 10.0,
    "budget_duration": "30d",
    "max_parallel_requests": 5,
    "tpm_limit": 100000,
    "rpm_limit": 60,
    "metadata": {"agent_id": "sre-agent-01"}
  }'
```

**Ответ:**
```json
{
  "key": "sk-sre-xxxxxxxxxxxxxxxx",
  "key_name": "sre-agent-01",
  "max_budget": 10.0,
  "expires": null
}
```

Ключ возвращается **только при создании**.

**Использование агентом:**
```
Authorization: Bearer sk-sre-xxxxxxxxxxxxxxxx
```

### Встроенные ограничения per key

| Параметр | Описание | Default для SRE-агента |
|---|---|---|
| `max_budget` | Бюджет в USD | 10.0 per 30d |
| `rpm_limit` | Requests per minute | 60 |
| `tpm_limit` | Tokens per minute | 100000 |
| `max_parallel_requests` | Concurrent streams | 5 |

При превышении → HTTP 429 с описанием (`RateLimitError` / `BudgetExceeded`).

### JWT (опциональный)

LiteLLM поддерживает JWT auth для сценариев с SSO/Teams:

```yaml
general_settings:
  enable_jwt_auth: true
  litellm_jwtauth:
    team_id_jwt_field: "team_id"
    user_id_jwt_field: "sub"
```

Для PoC используем Virtual Keys (проще). JWT — для расширения.

## Agent Registry Auth

Agent Registry — наш собственный сервис (FastAPI), не LiteLLM.

**Механизм:** Shared API key (`REGISTRY_API_KEY` в .env), проверяется middleware.

```python
async def registry_auth_middleware(request: Request, call_next: Callable) -> Response:
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not hmac.compare_digest(token, settings.registry_api_key):
        raise HTTPException(401, "Invalid registry API key")
    return await call_next(request)
```

## Per-Provider API Key Management

Ключи LLM-провайдеров (vLLM, OpenRouter) задаются в `config.yaml`:

```yaml
litellm_params:
  api_key: "os.environ/OPENROUTER_API_KEY"
```

- Ключи читаются из environment variables (не хранятся в БД)
- LiteLLM никогда не возвращает ключи через API
- В Docker: передаются через `env_file: .env`

## Ошибки

| Код | Когда |
|---|---|
| 401 | Отсутствует или невалидный ключ |
| 403 | Ключ валиден, но нет прав |
| 429 | Rate limit / budget exceeded |
