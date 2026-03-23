# System Design: AI-SRE Platform

## 1. Обзор системы

AI-SRE Platform — это инфраструктурная платформа, объединяющая два контура:

1. **Инфраструктурная платформа** — LLM API Gateway с балансировкой, A2A Agent Registry, observability-стек, guardrails и авторизация.
2. **SRE-агент** — автономный L1-агент диагностики инцидентов, работающий как потребитель платформы.

Платформа позволяет регистрировать A2A-агентов, подключать LLM-провайдеров, маршрутизировать запросы с учётом latency и health, собирать телеметрию и обеспечивать безопасность через guardrails и авторизацию.

---

## 2. Ключевые архитектурные решения

| Решение | Обоснование |
|---|---|
| **Codex CLI как ядро SRE-агента** | Production-ready shell execution с песочницей, approval modes, обработкой ошибок. Режимы `exec` и MCP server для автоматизации. Поддерживает любые OpenAI-compatible провайдеры. |
| **SSH доступ к полигону** | Codex подключается к полигону по SSH (не Docker socket). Изолированнее, реалистичнее, безопаснее — нет доступа к Docker daemon. |
| **LLM Gateway как единая точка входа** | Все LLM-запросы проходят через Gateway. Единая точка сбора метрик, маршрутизации и контроля доступа. OpenAI-compatible API (`/v1/chat/completions`). |
| **A2A Protocol (Google, v1.0)** | Открытый стандарт для inter-agent коммуникации. `a2a-sdk` для Python — async-first, поддержка JSON-RPC/HTTP/gRPC. |
| **Langfuse для трейсинга (два уровня)** | Уровень A: Gateway трейсит каждый LLM-запрос. Уровень B: парсинг `codex exec --json` stdout для agent-level трейсинга (tool calls, shell commands). |
| **Zabbix для мониторинга полигона** | Zabbix мониторит тестовый сервис (полигон), не саму платформу. Платформа мониторится через OpenTelemetry → Prometheus → Grafana. |
| **SQLAlchemy Async + Alembic** | ORM для PostgreSQL с автогенерацией миграций. Типизированные запросы, совместимость с Pydantic v2. |
| **structlog** | Structured JSON logging с автоматическим trace_id/span_id из OpenTelemetry. Корреляция логов с трейсами. |
| **opentelemetry-exporter-prometheus** | Единый OTel SDK для traces и metrics. Endpoint `/metrics` создаётся автоматически. |
| **intfloat/multilingual-e5-small** | Локальная embedding-модель для Qdrant (384-мерные векторы, CPU, русский/английский). Не зависит от платных API. |
| **Locust** | Нагрузочное тестирование на Python. Единый стек, web UI, достаточная производительность для PoC. |
| **Docker Compose для деплоя** | Все компоненты поднимаются одной командой. Достаточно для PoC, миграция на K8s — out of scope. |
| **pydantic-settings для конфигурации** | Все секреты и параметры — через `.env` и `BaseSettings`. Нет хардкода. |

---

## 3. Список модулей и их роли

### 3.1. LLM API Gateway (`gateway/`)

Прокси-сервер между потребителями (агентами) и LLM-провайдерами.

**Функции:**
- Приём запросов в формате OpenAI Chat Completions API
- SSE streaming pass-through (не буферизует ответ, проксирует поточно)
- Routing по имени модели → выбор провайдера
- Round-robin / weighted балансировка для реплик одной модели
- Latency-based routing: EMA latency → приоритет быстрому провайдеру
- Health-aware routing: circuit breaker при 5xx/timeout → провайдер выводится из пула → probe через configurable интервал
- Сбор метрик: RPS, latency (p50/p95), TTFT, TPOT, tokens in/out, cost per request, error rate
- Health-check endpoint `/health`
- Авторизация входящих запросов (JWT / API-key)
- Guardrails middleware (prompt injection filter, secret leak detection)

**Технологии:** FastAPI, httpx (async streaming), Pydantic v2, SQLAlchemy Async, structlog, opentelemetry-sdk, opentelemetry-exporter-prometheus

### 3.2. A2A Agent Registry (`registry/`)

Сервис реестра агентов по протоколу A2A.

**Функции:**
- Регистрация агентов с Agent Card (имя, описание, skills, capabilities, security schemes)
- Well-known endpoint `/.well-known/agent-card.json`
- CRUD операции: создание, получение, листинг, удаление агентов
- Валидация Agent Cards по спецификации A2A 1.0
- Хранение в PostgreSQL

**Технологии:** FastAPI, a2a-sdk, SQLAlchemy Async, Alembic

### 3.3. Provider Registry (`gateway/providers/`)

Подсистема внутри Gateway для динамического управления LLM-провайдерами.

**Функции:**
- CRUD API для провайдеров: URL, поддерживаемые модели, price_per_token, rate_limits, priority, weight
- Health state tracking (healthy / degraded / unhealthy)
- Latency statistics (EMA)
- Хранение в PostgreSQL, кэш в памяти

### 3.4. SRE-агент (`agent/`)

Автономный L1-агент диагностики инцидентов.

**Функции:**
- Приём алертов от Zabbix через webhook (FastAPI handler)
- Запуск Codex CLI в режиме `exec` (с `--json` для structured event stream) или через MCP server
- Codex подключается к полигону **по SSH** и выполняет read-only диагностику
- Поиск релевантных Runbooks в Qdrant через MCP tool
- Формирование структурированного отчёта → Telegram через MCP tool
- Регистрация как A2A-агент при старте
- Двухуровневый трейсинг в Langfuse: Gateway-level (A) + Agent-level через парсинг `--json` stdout (B)

**Технологии:** Codex CLI, FastAPI (webhook receiver), MCP, Qdrant client, Telegram Bot API, structlog

### 3.5. Observability Stack (`observability/`)

**Компоненты:**
- **OpenTelemetry SDK** — инструментирование Gateway и агента (traces + metrics)
- **Prometheus** — scrape и хранение метрик
- **Grafana** — дашборды (latency, RPS, error rates, token usage, cost, provider health)
- **Langfuse** — трейсинг LLM-вызовов и агентских цепочек

### 3.6. Полигон (`playground/`)

Тестовая среда для демонстрации работы SRE-агента.

**Компоненты:**
- Тестовое приложение (Python + FastAPI + PostgreSQL + Redis)
- SSH-сервер (OpenSSH) для доступа SRE-агента, пользователь `sre-agent` с ограниченными правами
- Генераторы нагрузки (bash-скрипты: stress CPU, fill RAM, flood disk with logs)
- Zabbix Server + Zabbix Agent на тестовом хосте
- Webhook интеграция: Zabbix → SRE-агент

### 3.7. Guardrails (`gateway/guardrails/`)

Middleware в Gateway для фильтрации небезопасных запросов.

**Функции:**
- Prompt injection detection (regex patterns + опциональный LLM-classifier)
- Secret leak detection (regex для API keys, паролей, токенов, приватных ключей)
- Configurable rules (включение/отключение фильтров, whitelist)
- Логирование срабатываний

### 3.8. Auth (`gateway/auth/`)

Подсистема авторизации.

**Функции:**
- Валидация JWT / API-key на входе Gateway
- Управление токенами агентов (CRUD)
- Per-provider API key management (зашифрованные ключи в PostgreSQL)

---

## 4. Основной Workflow выполнения задачи

### 4.1. Штатный сценарий: инцидент → диагностика → отчёт

```
1. [Генератор нагрузки] Стресс-скрипт создаёт аномалию в тестовом сервисе
        │
2. [Zabbix] Детектирует аномалию (CPU > 90%, RAM > 85%, Disk > 95%)
        │
3. [Zabbix → Webhook] POST /webhooks/zabbix → SRE-агент (FastAPI handler)
        │  Payload: host, trigger, severity, timestamp, description
        │
4. [Webhook Handler] Валидирует payload, формирует промпт для Codex
        │  Включает: контекст алерта + инструкции из AGENTS.md
        │
5. [Codex exec] Запускается с промптом, auth token для Gateway
        │
6. [Codex → Gateway] POST /v1/chat/completions (SSE stream)
        │  Header: Authorization: Bearer <agent-token>
        │
7. [Gateway]
        │  a. Auth middleware: валидация токена
        │  b. Guardrails middleware: проверка промпта
        │  c. Router: выбор провайдера по модели + latency/health
        │  d. Proxy: streaming pass-through к провайдеру
        │  e. Metrics: TTFT, TPOT, tokens, cost, latency
        │
8. [LLM Provider] vLLM / OpenRouter → ответ (SSE stream)
        │
9. [Codex] Получает ответ, решает выполнить bash-команду
        │  (ssh playground top, ssh playground df -h, etc.)
        │
10. [Codex → SSH → Playground] Выполняет read-only команду через SSH
         │
11. [Codex] Анализирует stdout/stderr, при необходимости:
         │  - Повторяет шаги 6-10 (цикл диагностики)
         │  - Ищет Runbook через MCP tool → Qdrant
         │
12. [Codex → MCP Tool: Qdrant] Векторный поиск по базе Runbooks
         │
13. [Codex] Формирует финальный отчёт
         │
14. [Codex → MCP Tool: Telegram] Отправляет отчёт в Telegram
         │
15. [Langfuse] Весь trace записан:
         │  - Уровень A (Gateway): каждый LLM-запрос (provider, tokens, cost, latency)
         │  - Уровень B (Agent): парсинг codex --json stdout (tool calls, shell commands, reasoning)
```

### 4.2. Сценарий failover провайдера

```
1. [Gateway] Запрос к Provider A → timeout (> 30s) или 5xx
        │
2. [Circuit Breaker] Provider A → состояние OPEN (excluded из пула)
        │
3. [Router] Перенаправляет запрос к Provider B (следующий по приоритету)
        │
4. [Probe] Через N секунд → тестовый запрос к Provider A
        │  Если OK → HALF-OPEN → если стабильно → CLOSED (возврат в пул)
        │  Если FAIL → остаётся OPEN, probe через 2N секунд
```

---

## 5. State / Memory / Context Handling

### 5.1. Состояние Gateway

| Что | Где хранится | TTL |
|---|---|---|
| Список провайдеров + конфигурация | PostgreSQL (persistent) + in-memory cache | Cache: 30s |
| Health state провайдеров (OPEN/CLOSED/HALF-OPEN) | In-memory (per-instance) | Reset при рестарте |
| EMA latency провайдеров | In-memory (per-instance) | Accumulates, reset при рестарте |
| Метрики (counters, histograms) | In-memory → Prometheus scrape | Prometheus retention |
| API keys агентов | PostgreSQL (encrypted) | Persistent |

### 5.2. Состояние SRE-агента

| Что | Где хранится | TTL |
|---|---|---|
| Контекст текущего расследования | Codex session (in-memory) | Время жизни сессии |
| Runbooks | Qdrant (persistent) | Persistent, обновляется вручную |
| История алертов | Не хранится в PoC | — |
| Agent Card | A2A Registry → PostgreSQL | Persistent |

### 5.3. Context Budget

Codex управляет контекстным окном самостоятельно. На уровне платформы:
- Gateway не хранит контекст диалога — он stateless прокси
- Каждый запрос к Gateway — независимый (контекст в теле запроса от Codex)
- Qdrant результаты обрезаются до top-K (K=3) для экономии токенов

---

## 6. Retrieval-контур

### 6.1. Qdrant — база знаний Runbooks

**Источники:** Markdown-файлы с Runbooks (инструкции по типовым инцидентам).

**Индексация:**
- При старте/обновлении: парсинг `.md` файлов → chunking → embedding (модель: `intfloat/multilingual-e5-small`, 384-мерные векторы, CPU, локально через `sentence-transformers`) → upsert в Qdrant

**Поиск:**
- MCP tool `qdrant_search` доступен Codex
- Input: текстовый запрос (описание инцидента)
- Process: embedding запроса → cosine similarity → top-K results
- Output: текст релевантных Runbook-секций

**Ограничения:**
- Top-K = 3 (баланс между полнотой и context budget)
- Минимальный score threshold = 0.7 (фильтрация нерелевантных результатов)
- Chunk size: ~512 tokens с overlap 64 tokens

---

## 7. Tool / API интеграции

### 7.1. Codex MCP Tools (кастомные)

| Tool | Описание | Side effects | Timeout |
|---|---|---|---|
| `qdrant_search` | Поиск Runbooks по описанию инцидента | Read-only | 5s |
| `telegram_send` | Отправка отчёта в Telegram-чат | Write (external) | 10s |

### 7.2. Codex Built-in Tools

| Tool | Описание | Ограничения |
|---|---|---|
| Shell execution | Команды через SSH к полигону (`ssh playground <cmd>`) | Пользователь sre-agent без write-прав, whitelist команд в AGENTS.md |
| File read | Чтение файлов через SSH (`ssh playground cat ...`) | Read-only, truncation через tail/head |

### 7.3. External APIs

| API | Назначение | Auth | Error handling |
|---|---|---|---|
| Zabbix Webhook | Входящие алерты | Shared secret в header | Validate payload, 400 on malformed |
| LLM Providers (vLLM, OpenRouter) | Генерация текста | API key (per-provider, encrypted) | Circuit breaker, retry с backoff |
| Telegram Bot API | Отправка отчётов | Bot token | Retry 3x с backoff, log on failure |
| Qdrant API | Векторный поиск | API key (optional) | Timeout 5s, fallback: skip retrieval |

### 7.4. Контракты и защита

- **Все LLM-запросы** проходят через Gateway → guardrails → auth → routing
- **Shell-команды** выполняются через SSH к полигону. Whitelist: cat, ls, grep, top, df, docker stats/logs, journalctl, tail, head, ps, free, netstat. Пользователь `sre-agent` без write-прав.
- **Запрещённые паттерны:** rm, kill, reboot, shutdown, mkfs, dd, операторы записи (>), pipe к деструктивным командам
- **Timeout на shell:** 30s per command, 5 минут на полный цикл диагностики
- **Rate limiting:** Gateway ограничивает RPS per agent token

---

## 8. Failure Modes, Fallback и Guardrails

### 8.1. Failure Modes

| Failure | Detect | Protect | Residual Risk |
|---|---|---|---|
| **LLM Provider недоступен** | Health-check probe, timeout > 30s, 5xx | Circuit breaker → fallback provider | Если все провайдеры down → 503 клиенту |
| **LLM Provider медленный** | EMA latency выше порога | Latency-based routing отдаёт приоритет быстрому | При общей деградации — повышенная latency |
| **Prompt injection через логи** | Guardrails middleware (regex + classifier) | Блокировка запроса, логирование | FP/FN классификатора |
| **Утечка секретов в промпте** | Regex filter в Guardrails | Блокировка, маскирование | Нестандартные форматы секретов |
| **Codex зацикливается** | Лимит итераций (max_steps), timeout сессии | Принудительное завершение сессии | Потеря частичных результатов |
| **Переполнение контекста** | Codex управляет самостоятельно | Truncation вывода shell (max 4000 chars) | Потеря информации в длинных логах |
| **Qdrant недоступен** | Timeout 5s на MCP tool call | Fallback: агент работает без Runbooks | Снижение качества диагностики |
| **Telegram недоступен** | HTTP error от Bot API | Retry 3x, логирование отчёта в Langfuse | Отчёт не доставлен в чат |
| **Zabbix шлёт дубли** | Дедупликация по alert ID + timestamp | Idempotent handler: skip если уже обработан | Окно дедупликации ограничено |
| **Опасная команда от LLM** | Whitelist бинарников + regex фильтр | Блокировка команды, stderr в контекст | Обход через цепочку safe-команд |

### 8.2. Стратегия Graceful Degradation

```
Все провайдеры UP → штатная работа
    │
Provider A DOWN → circuit breaker → route to Provider B
    │
Все провайдеры DOWN → 503 + alert в Grafana
    │
Qdrant DOWN → агент работает без RAG (только LLM reasoning)
    │
Telegram DOWN → отчёт сохраняется в Langfuse trace
    │
Langfuse DOWN → метрики и логи всё равно в Prometheus/stdout
```

---

## 9. Технические и операционные ограничения

### 9.1. Latency

| Операция | Target | Max |
|---|---|---|
| Gateway routing decision | < 5ms | 20ms |
| LLM TTFT (vLLM, local) | < 500ms | 2s |
| LLM TTFT (OpenRouter) | < 1s | 5s |
| Полный цикл диагностики | < 3 min | 5 min |
| Qdrant search | < 100ms | 500ms |

### 9.2. Cost

| Параметр | Значение |
|---|---|
| Бюджет на LLM per incident | Отслеживается через Gateway (tokens × price_per_token) |
| Средний запрос | ~2000 input tokens, ~1000 output tokens |
| Цикл диагностики | ~5-10 LLM-вызовов |

### 9.3. Reliability

| Параметр | Target |
|---|---|
| Gateway uptime | 99.5% (PoC, single instance) |
| Circuit breaker recovery time | 30s probe → 60s → 120s (exponential backoff) |
| Max concurrent investigations | 5 (ограничение Codex sessions) |
| Data retention (Langfuse) | 14 дней |
| Data retention (Prometheus) | 30 дней |

### 9.4. Security

- Все inter-service коммуникации внутри Docker network (не exposed наружу)
- LLM API keys зашифрованы в PostgreSQL (Fernet)
- Agent tokens — JWT / API-key с expiration
- SSH доступ к полигону: отдельный пользователь `sre-agent` без write-прав, SSH-ключ в Docker secret
- Whitelist shell-команд на уровне AGENTS.md
- Guardrails в Gateway: prompt injection filter, secret leak detection
