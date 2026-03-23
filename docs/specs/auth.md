# Спецификация: Auth (Авторизация)

## Назначение

Контроль доступа к LLM Gateway и Agent Registry. Агенты и внешние клиенты должны предъявить валидный токен для использования платформы.

## Механизм

### API Key (основной для PoC)

Простой статический токен, выданный агенту при регистрации.

```
Authorization: Bearer <api-key>
```

**Хранение:**
- Ключи хранятся в PostgreSQL, зашифрованы Fernet (симметричное шифрование)
- Fernet key — из переменной среды `ENCRYPTION_KEY`
- В таблице хранится: `key_hash` (SHA-256 для быстрого lookup) + `key_encrypted` (для расшифровки при необходимости)

**Таблица `api_keys`:**
```sql
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    key_hash TEXT NOT NULL UNIQUE,
    key_encrypted TEXT NOT NULL,
    name TEXT NOT NULL,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    expires_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ
);
```

### JWT (опциональный, для расширения)

Для сценариев с expiration и claims:

```python
class JWTPayload(BaseModel):
    sub: str          # agent_id
    exp: datetime     # expiration
    iat: datetime     # issued at
    scope: list[str]  # ["llm:chat", "registry:read"]
```

**Signing:** HS256, secret из `JWT_SECRET` env var.

## API для управления ключами

```
POST   /auth/keys              — создание ключа для агента
GET    /auth/keys              — список ключей (admin)
DELETE /auth/keys/{key_id}     — отзыв ключа
```

### Создание ключа

```
POST /auth/keys
{
  "agent_id": "sre-agent-01",
  "name": "production-key",
  "expires_at": "2026-12-31T23:59:59Z"  // optional
}
```

**Ответ:**
```json
{
  "key_id": "uuid",
  "api_key": "sk-sre-xxxxxxxxxxxxxxxx",
  "agent_id": "sre-agent-01",
  "name": "production-key",
  "expires_at": "2026-12-31T23:59:59Z"
}
```

`api_key` возвращается **только при создании**. После этого доступен только `key_id`.

## Per-Provider API Key Management

Ключи для LLM-провайдеров (OpenRouter API key, vLLM token):

- Хранятся в таблице `providers`, поле `api_key_encrypted`
- Шифрование: Fernet
- Gateway расшифровывает ключ при проксировании запроса к провайдеру
- Ключи никогда не возвращаются через API (только `***masked***`)

## Auth Middleware (Gateway)

```python
async def auth_middleware(request: Request, call_next):
    token = extract_bearer_token(request)
    if not token:
        raise HTTPException(401, "Missing authorization token")

    agent = await validate_token(token)
    if not agent:
        raise HTTPException(401, "Invalid or expired token")

    request.state.agent_id = agent.agent_id
    request.state.scopes = agent.scopes

    return await call_next(request)
```

## Rate Limiting (per agent)

| Параметр | Default |
|---|---|
| Requests per minute | 60 |
| Requests per hour | 1000 |
| Concurrent streams | 5 |

Лимиты configurable per agent через `api_keys` metadata.

Реализация: in-memory sliding window counter (per agent_id). При превышении → HTTP 429 с `Retry-After` header.

## Ошибки

| Код | Когда |
|---|---|
| 401 | Отсутствует или невалидный токен |
| 403 | Токен валиден, но нет прав (scope) |
| 429 | Rate limit exceeded |
