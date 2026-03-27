# System Design: AI-SRE Platform

## 1. Обзор системы

AI-SRE Platform — инфраструктурная платформа с двумя контурами:

1. **Инфраструктурная платформа** — LLM API Gateway (LiteLLM), A2A Agent Registry, observability-стек, guardrails и авторизация.
2. **SRE-агент** — автономный L1-агент диагностики инцидентов, работающий как потребитель платформы.

---

## 2. Ключевые архитектурные решения

| Решение | Обоснование |
|---|---|
| **LiteLLM Proxy** как LLM Gateway | Production-ready OpenAI-compatible прокси. Из коробки: multi-provider routing (latency-based, weighted), circuit breaker, failover, виртуальные ключи, Prometheus метрики, Langfuse интеграция, cost tracking, rate limiting. Писать свой Gateway с нуля нецелесообразно — LiteLLM покрывает 90%+ требований. |
| **Кастомные Guardrails** для LiteLLM | LiteLLM имеет framework `CustomGuardrail`. Пишем свои: prompt injection (regex) и secret leak (regex). Не зависим от enterprise-лицензии и внешних API. |
| **Codex CLI** как ядро агента | Production-ready shell execution, MCP client, `exec` / MCP server режимы, любые OpenAI-compatible провайдеры |
| **SSH** доступ к полигону | Изоляция (нет доступа к Docker daemon), реалистичность, безопасность |
| **A2A Protocol v1.0** (`a2a-sdk`) | Открытый стандарт inter-agent коммуникации, async-first Python SDK |
| **Langfuse** (два уровня) | A: LiteLLM трейсит каждый LLM-запрос (native integration). B: парсинг `codex exec --json` для agent-level трейсинга |
| **Zabbix** → полигон | Мониторит тестовый сервис (не платформу). Платформа: LiteLLM Prometheus + Grafana |
| **SQLAlchemy Async + Alembic** | ORM для Agent Registry и собственных сервисов. LiteLLM использует свою Prisma-миграцию для внутренней БД |
| **structlog** | JSON logging с trace_id/span_id для наших сервисов (Agent, Registry) |
| **intfloat/multilingual-e5-small** | Локальная embedding-модель (384d, CPU, русский/английский) |
| **Locust** | Нагрузочное тестирование на Python, единый стек |
| **Docker Compose** | Все компоненты одной командой. K8s — out of scope |
| **pydantic-settings** | Секреты и параметры через `.env` + `BaseSettings` (для Agent, Registry) |

---

## 3. Модули

| Модуль | Роль | Спецификация |
|---|---|---|
| **LLM API Gateway** (LiteLLM Proxy) | OpenAI-compatible прокси: routing, балансировка, circuit breaker, SSE streaming, auth, метрики, cost tracking, Langfuse | [llm-gateway.md](specs/llm-gateway.md) |
| **Guardrails** (CustomGuardrail для LiteLLM) | Prompt injection detection, secret leak filter — кастомный код, подключаемый в LiteLLM config | [guardrails.md](specs/guardrails.md) |
| **A2A Agent Registry** (`registry/`) | Реестр агентов: CRUD Agent Cards, well-known endpoint, валидация по A2A v1.0 | [agent-registry.md](specs/agent-registry.md) |
| **SRE-агент** (`agent/`) | Webhook handler → Codex exec → SSH диагностика → Qdrant → Telegram | [sre-agent.md](specs/sre-agent.md) |
| **Observability** | LiteLLM → Prometheus → Grafana + Langfuse (self-hosted) | [observability.md](specs/observability.md) |
| **Полигон** (`playground/`) | Python FastAPI app + PostgreSQL + Redis + SSH-сервер + Zabbix Agent | [serving-config.md](specs/serving-config.md) |

---

## 4. Основной Workflow

### 4.1. Штатный сценарий

```
1. [Генератор нагрузки] Стресс-скрипт → аномалия в тестовом сервисе
2. [Zabbix] Детектирует (CPU > 90%, RAM > 85%, Disk > 95%)
3. [Zabbix → Webhook] POST /webhooks/zabbix → SRE-агент
4. [Webhook Handler] Валидация, дедупликация, формирование промпта → Codex exec --json
5. [Codex → LiteLLM] POST /v1/chat/completions (SSE stream)
6. [LiteLLM] Auth (virtual key) → Guardrails → Router (latency-based) → Provider
7. [Codex] Получает ответ → ssh playground <command> (read-only)
8. [Codex] Цикл: LLM → shell → анализ → (повтор или Qdrant search)
9. [Codex → MCP: telegram_send] Отчёт в Telegram
10.[Langfuse] Trace: A (LiteLLM: LLM-запросы) + B (Agent: tool/shell/reasoning)
```

Детальная схема с ветками ошибок: [workflow.md](diagrams/workflow.md)

### 4.2. Failover провайдера

```
Provider A timeout/5xx → cooldown (excluded) → route to Provider B
Health check через 30s → OK: возврат в пул | FAIL: остаётся в cooldown
```

Детали: [llm-gateway.md](specs/llm-gateway.md#circuit-breaker--failover)

---

## 5. State / Memory / Context

### LiteLLM Gateway

| Что | Где | TTL |
|---|---|---|
| Модели + провайдеры | `config.yaml` + PostgreSQL (LiteLLM DB) | Persistent |
| Virtual keys, spend tracking | PostgreSQL (LiteLLM DB) | Persistent |
| Deployment health (cooldown state) | In-memory | Reset при рестарте |
| Latency stats per deployment | In-memory | Reset при рестарте |

### SRE-агент

| Что | Где | TTL |
|---|---|---|
| Контекст расследования | Codex session (in-memory) | Время жизни сессии |
| Runbooks | Qdrant | Persistent, обновляется вручную |
| Agent Card | A2A Registry → PostgreSQL | Persistent |

**Context budget:** Codex управляет контекстным окном самостоятельно. LiteLLM — stateless прокси (контекст в теле запроса от Codex).

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
| LLM Providers | vLLM, OpenRouter через LiteLLM | Cooldown + failover (LiteLLM built-in) |

Whitelist shell-команд и контракты: [sre-agent.md](specs/sre-agent.md)

---

## 8. Failure Modes и Graceful Degradation

| Failure | Protect | Residual Risk |
|---|---|---|
| LLM Provider down | LiteLLM cooldown → fallback deployment | Все down → 503 |
| LLM Provider slow | Latency-based routing (LiteLLM) | Общая деградация |
| Prompt injection | CustomGuardrail (regex + classifier) | FP/FN |
| Secret leak | CustomGuardrail (regex) | Нестандартные форматы |
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
| LiteLLM routing | < 5ms | 20ms |
| TTFT (vLLM) | < 500ms | 2s |
| TTFT (OpenRouter) | < 1s | 5s |
| Полный цикл диагностики | < 3 min | 5 min |
| Qdrant search | < 100ms | 500ms |

### Cost

| Параметр | Значение |
|---|---|
| Бюджет per incident | Отслеживается LiteLLM (spend tracking per virtual key) |
| Средний запрос | ~2000 input + ~1000 output tokens |
| Цикл диагностики | ~5-10 LLM-вызовов |

### Reliability & Security

| Параметр | Target |
|---|---|
| Gateway uptime | 99.5% (PoC, single instance) |
| Cooldown recovery | 30s → 60s (LiteLLM built-in) |
| Max concurrent investigations | 5 |
| Retention: Langfuse / Prometheus | 14 / 30 дней |

**Security:** Docker network isolation, LiteLLM virtual keys + budget limits, SSH с restricted user, whitelist shell-команд, CustomGuardrails в LiteLLM. Детали: [auth.md](specs/auth.md)
