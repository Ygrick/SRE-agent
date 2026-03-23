# System Design: AI-SRE Platform

## 1. Обзор системы

AI-SRE Platform — инфраструктурная платформа с двумя контурами:

1. **Инфраструктурная платформа** — LLM API Gateway с балансировкой, A2A Agent Registry, observability-стек, guardrails и авторизация.
2. **SRE-агент** — автономный L1-агент диагностики инцидентов, работающий как потребитель платформы.

---

## 2. Ключевые архитектурные решения

| Решение | Обоснование |
|---|---|
| **Codex CLI** как ядро агента | Production-ready shell execution, MCP client, `exec` / MCP server режимы, любые OpenAI-compatible провайдеры |
| **SSH** доступ к полигону | Изоляция (нет доступа к Docker daemon), реалистичность, безопасность |
| **LLM Gateway** | Единая точка сбора метрик, маршрутизации и контроля доступа. OpenAI-compatible API |
| **A2A Protocol v1.0** (`a2a-sdk`) | Открытый стандарт inter-agent коммуникации, async-first Python SDK |
| **Langfuse** (два уровня) | A: Gateway трейсит LLM-запросы. B: парсинг `codex exec --json` для agent-level трейсинга |
| **Zabbix** → полигон | Мониторит тестовый сервис (не платформу). Платформа: OTel → Prometheus → Grafana |
| **SQLAlchemy Async + Alembic** | ORM + автогенерация миграций, совместимость с Pydantic v2 |
| **structlog** | JSON logging с trace_id/span_id из OTel |
| **OTel exporter → Prometheus** | Единый SDK для traces и metrics, `/metrics` endpoint автоматически |
| **intfloat/multilingual-e5-small** | Локальная embedding-модель (384d, CPU, русский/английский) |
| **Locust** | Нагрузочное тестирование на Python, единый стек |
| **Docker Compose** | Все компоненты одной командой. K8s — out of scope |
| **pydantic-settings** | Секреты и параметры через `.env` + `BaseSettings` |

---

## 3. Модули

| Модуль | Роль | Спецификация |
|---|---|---|
| **LLM API Gateway** (`gateway/`) | Прокси LLM-запросов: routing по модели, балансировка (RR/weighted/latency-based), circuit breaker, SSE streaming, guardrails, auth, метрики | [llm-gateway.md](specs/llm-gateway.md) |
| **A2A Agent Registry** (`registry/`) | Реестр агентов: CRUD Agent Cards, well-known endpoint, валидация по A2A v1.0 | [agent-registry.md](specs/agent-registry.md) |
| **Provider Registry** (`gateway/providers/`) | Динамическое управление LLM-провайдерами: CRUD, health tracking, EMA latency | [llm-gateway.md](specs/llm-gateway.md) |
| **SRE-агент** (`agent/`) | Webhook handler → Codex exec → SSH диагностика → Qdrant → Telegram | [sre-agent.md](specs/sre-agent.md) |
| **Observability** | OTel SDK → Prometheus → Grafana + Langfuse (self-hosted) | [observability.md](specs/observability.md) |
| **Полигон** (`playground/`) | Python FastAPI app + PostgreSQL + Redis + SSH-сервер + Zabbix Agent | [serving-config.md](specs/serving-config.md) |
| **Guardrails** (`gateway/guardrails/`) | Prompt injection detection, secret leak filter | [guardrails.md](specs/guardrails.md) |
| **Auth** (`gateway/auth/`) | JWT / API-key валидация, per-provider key management | [auth.md](specs/auth.md) |

---

## 4. Основной Workflow

### 4.1. Штатный сценарий

```
1. [Генератор нагрузки] Стресс-скрипт → аномалия в тестовом сервисе
2. [Zabbix] Детектирует (CPU > 90%, RAM > 85%, Disk > 95%)
3. [Zabbix → Webhook] POST /webhooks/zabbix → SRE-агент
4. [Webhook Handler] Валидация, дедупликация, формирование промпта → Codex exec --json
5. [Codex → Gateway] POST /v1/chat/completions (SSE stream)
6. [Gateway] Auth → Guardrails → Router (model + latency/health) → Proxy → Provider
7. [Codex] Получает ответ → ssh playground <command> (read-only)
8. [Codex] Цикл: LLM → shell → анализ → (повтор или Qdrant search)
9. [Codex → MCP: telegram_send] Отчёт в Telegram
10.[Langfuse] Trace: A (Gateway: LLM-запросы) + B (Agent: tool/shell/reasoning)
```

Детальная схема с ветками ошибок: [workflow.md](diagrams/workflow.md)

### 4.2. Failover провайдера

```
Provider A timeout/5xx → Circuit Breaker: OPEN → route to Provider B
Probe через 30s → OK: HALF-OPEN → CLOSED | FAIL: OPEN, probe через 60s
```

Детали circuit breaker: [llm-gateway.md](specs/llm-gateway.md#circuit-breaker)

---

## 5. State / Memory / Context

### Gateway (stateless прокси, state в памяти и PostgreSQL)

| Что | Где | TTL |
|---|---|---|
| Провайдеры + конфигурация | PostgreSQL + in-memory cache | Cache: 30s |
| Health state (OPEN/CLOSED/HALF-OPEN) | In-memory | Reset при рестарте |
| EMA latency | In-memory | Reset при рестарте |
| API keys | PostgreSQL (Fernet-encrypted) | Persistent |

### SRE-агент

| Что | Где | TTL |
|---|---|---|
| Контекст расследования | Codex session (in-memory) | Время жизни сессии |
| Runbooks | Qdrant | Persistent, обновляется вручную |
| Agent Card | A2A Registry → PostgreSQL | Persistent |

**Context budget:** Codex управляет контекстным окном самостоятельно. Gateway — stateless (контекст в теле запроса от Codex).

---

## 6. Retrieval-контур

Векторная база Runbooks в Qdrant. Embedding: `intfloat/multilingual-e5-small` (384d, CPU, `sentence-transformers`).

Pipeline: `runbooks/*.md → chunking по H1/H2 → embedding → Qdrant`

Поиск: MCP tool `qdrant_search` → cosine similarity → top-3, score > 0.7

Детали: [retriever.md](specs/retriever.md)

---

## 7. Tool / API интеграции

| Tool / API | Назначение | Error handling |
|---|---|---|
| `qdrant_search` (MCP) | Поиск Runbooks | Timeout 5s, fallback: без RAG |
| `telegram_send` (MCP) | Отчёт в Telegram | Retry 3x, fallback: log в Langfuse |
| Shell via SSH | `ssh playground <cmd>` — read-only диагностика | Timeout 30s, whitelist команд |
| Zabbix Webhook | Входящие алерты | Validate payload, дедупликация |
| LLM Providers | vLLM, OpenRouter через Gateway | Circuit breaker, retry |

Whitelist shell-команд и контракты: [sre-agent.md](specs/sre-agent.md)

---

## 8. Failure Modes и Graceful Degradation

| Failure | Protect | Residual Risk |
|---|---|---|
| LLM Provider down | Circuit breaker → fallback | Все down → 503 |
| LLM Provider slow | Latency-based routing | Общая деградация |
| Prompt injection | Guardrails (regex + classifier) | FP/FN |
| Secret leak | Regex filter | Нестандартные форматы |
| Codex loop | Max 15 команд, timeout 5 min | Потеря partial results |
| Context overflow | Codex built-in + truncation 4000 chars | Потеря информации |
| Qdrant down | Fallback: без RAG | Снижение качества |
| Telegram down | Retry 3x → log в Langfuse | Не доставлен |
| Zabbix дубли | Дедупликация по alert_id | Окно TTL 10 min |

**Degradation chain:**
```
Provider A DOWN → route to B → Все DOWN → 503 + Grafana alert
Qdrant DOWN → без RAG │ Telegram DOWN → log в Langfuse │ Langfuse DOWN → Prometheus + stdout
```

---

## 9. Ограничения

### Latency

| Операция | Target | Max |
|---|---|---|
| Gateway routing | < 5ms | 20ms |
| TTFT (vLLM) | < 500ms | 2s |
| TTFT (OpenRouter) | < 1s | 5s |
| Полный цикл диагностики | < 3 min | 5 min |
| Qdrant search | < 100ms | 500ms |

### Cost

| Параметр | Значение |
|---|---|
| Бюджет per incident | Отслеживается через Gateway (tokens × price) |
| Средний запрос | ~2000 input + ~1000 output tokens |
| Цикл диагностики | ~5-10 LLM-вызовов |

### Reliability & Security

| Параметр | Target |
|---|---|
| Gateway uptime | 99.5% (PoC, single instance) |
| Circuit breaker recovery | 30s → 60s → 120s (exp. backoff) |
| Max concurrent investigations | 5 |
| Retention: Langfuse / Prometheus | 14 / 30 дней |

**Security:** Docker network isolation, Fernet-encrypted keys в PostgreSQL, SSH с restricted user, whitelist shell-команд, guardrails в Gateway. Детали: [auth.md](specs/auth.md)
