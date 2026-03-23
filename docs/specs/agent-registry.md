# Спецификация: A2A Agent Registry

## Назначение

Сервис реестра A2A-агентов. Позволяет регистрировать агентов с Agent Card, получать список или конкретную карточку. Реализован по спецификации A2A Protocol v1.0.

## Протокол

Используется `a2a-sdk` для Python. Поддерживается HTTP/REST binding (основной) и JSON-RPC 2.0 (опциональный).

## API

### Well-Known Endpoint (A2A spec)

```
GET /.well-known/agent-card.json  →  Agent Card самого Registry (как A2A-сервиса)
```

### Agent CRUD (Registry-specific)

```
POST   /agents              — регистрация агента (принимает Agent Card JSON)
GET    /agents              — список всех агентов (с фильтрацией по skills, name)
GET    /agents/{agent_id}   — получение Agent Card по ID
PUT    /agents/{agent_id}   — обновление Agent Card
DELETE /agents/{agent_id}   — удаление агента
```

### A2A Protocol Endpoints (per agent)

Проксирование A2A-запросов к зарегистрированным агентам:

```
POST   /v1/agents/{agentId}/tasks:sendMessage
POST   /v1/agents/{agentId}/tasks:sendStreamingMessage
GET    /v1/agents/{agentId}/tasks/{taskId}
POST   /v1/agents/{agentId}/tasks/{taskId}:cancel
GET    /v1/agents/{agentId}/card:extended
```

## Agent Card (A2A v1.0)

Пример Agent Card для SRE-агента:

```json
{
  "id": "sre-agent-01",
  "name": "AI-SRE L1 Diagnostics Agent",
  "description": "Автономный агент первичной диагностики инфраструктурных инцидентов. Принимает алерты от Zabbix, выполняет read-only диагностику через терминал, ищет релевантные Runbooks и формирует отчёт.",
  "version": "0.1.0",
  "baseUrl": "http://sre-agent:8002",
  "provider": {
    "name": "AI-SRE Platform",
    "url": "https://github.com/user/sre-agent"
  },
  "capabilities": {
    "streaming": true,
    "pushNotifications": false,
    "extendedAgentCard": false
  },
  "skills": [
    {
      "id": "diagnose-incident",
      "name": "Diagnose Infrastructure Incident",
      "description": "Принимает Zabbix alert, выполняет диагностику через терминал, возвращает отчёт с root cause и рекомендациями"
    }
  ],
  "securitySchemes": {
    "apiKey": {
      "type": "apiKey",
      "in": "header",
      "name": "Authorization"
    }
  },
  "security": [
    {"apiKey": []}
  ],
  "interfaces": [
    {"type": "http", "version": "1.0"}
  ]
}
```

## Хранение

- **PostgreSQL** — таблица `agents`:
  - `id` (UUID, PK)
  - `agent_id` (TEXT, UNIQUE) — ID из Agent Card
  - `card` (JSONB) — полный Agent Card
  - `is_active` (BOOLEAN)
  - `registered_at` (TIMESTAMPTZ)
  - `updated_at` (TIMESTAMPTZ)
  - `last_health_check` (TIMESTAMPTZ, nullable)
  - `health_status` (TEXT: healthy / unhealthy / unknown)

## Валидация

- Agent Card валидируется по JSON Schema из A2A spec (через `a2a-sdk`)
- Обязательные поля: `id`, `name`, `version`, `baseUrl`, `securitySchemes`, `security`, `interfaces`
- `baseUrl` должен быть доступен (опциональный health probe при регистрации)

## Health Monitoring агентов

- Периодический (configurable, default 60s) health probe к `baseUrl` каждого агента
- При недоступности → `health_status = unhealthy`
- Не удаляет агента из реестра, только помечает

## Фильтрация и поиск

```
GET /agents?skill=diagnose-incident
GET /agents?name=sre
GET /agents?health_status=healthy
```

## Ошибки

| Код | Когда |
|---|---|
| 400 | Невалидный Agent Card |
| 404 | Агент не найден |
| 409 | Агент с таким ID уже зарегистрирован |

## Зависимости

- **PostgreSQL** — хранение Agent Cards
- **a2a-sdk** — валидация, протокол
