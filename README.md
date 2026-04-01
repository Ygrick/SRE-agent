# AI-SRE Platform: Автономный L1-агент диагностики инцидентов

## Что за задача

Современные микросервисные инфраструктуры генерируют большое количество рутинных алертов (CPU, RAM, диск). Дежурные L1-инженеры тратят время на однотипные операции: SSH → `top` → `df -h` → Runbook → передать L2.

**AI-SRE Platform** автоматизирует сбор контекста и формирование первичной гипотезы.

## Что делает PoC

1. Генератор нагрузки создаёт аномалию в тестовом сервисе (полигон)
2. Zabbix фиксирует и отправляет webhook
3. SRE-агент подключается к серверу по **SSH**, выполняет диагностику (`top`, `df`, `free`, `ps`)
4. Ищет релевантный **Runbook** в Qdrant (RAG)
5. LLM анализирует данные и формирует отчёт
6. Отчёт отправляется в **Telegram**
7. Все LLM-запросы проходят через **LiteLLM Gateway** (балансировка, метрики, guardrails)
8. Трейсы в **Langfuse**, метрики в **Prometheus → Grafana**

---

## Развёртывание

### Предварительные требования

- Docker 24.0+ и Docker Compose v2
- Python 3.12+ и [uv](https://docs.astral.sh/uv/)
- (Опционально) NVIDIA GPU для локального vLLM — см. [deploy-vllm.md](docs/guides/deploy-vllm.md)

### Шаг 1: Клонирование и настройка переменных окружения

```bash
git clone https://github.com/Ygrick/SRE-agent.git && cd SRE-agent
cp .env.example .env
```

Отредактируйте `.env` — заполните обязательные поля:

```env
# PostgreSQL (единый пользователь для всех БД)
POSTGRES_PASSWORD=<ваш-пароль>

# LiteLLM Gateway
LITELLM_MASTER_KEY=sk-master-<ваш-ключ>

# LLM-провайдер (OpenRouter)
OPENROUTER_API_KEY=sk-or-...

# Langfuse (оставьте defaults для локального деплоя)
LANGFUSE_PUBLIC_KEY=pk-lf-local
LANGFUSE_SECRET_KEY=sk-lf-local

# Telegram (для получения отчётов)
AGENT_TELEGRAM_BOT_TOKEN=<token от @BotFather>
AGENT_TELEGRAM_CHAT_ID=<ваш chat_id>

# Agent Registry
REGISTRY_API_KEY=<ваш-ключ>
```

> **Telegram бот:** создайте через [@BotFather](https://t.me/BotFather), отправьте `/start` боту, узнайте chat_id через `https://api.telegram.org/bot<TOKEN>/getUpdates`

### Шаг 2: Настройка LLM-провайдеров в LiteLLM

Отредактируйте `gateway/litellm_config.yaml` — укажите ваши LLM-провайдеры:

```yaml
model_list:
  # OpenRouter (free tier)
  - model_name: "step-3.5-flash"       # primary
    litellm_params:
      model: "openai/stepfun/step-3.5-flash:free"
      api_base: "https://openrouter.ai/api/v1"
      api_key: "os.environ/OPENROUTER_API_KEY"
    model_info:
      id: "openrouter-step-3.5-flash"
      priority: 0

  # Опционально: собственный vLLM gpt-oss-20b на GPU
  # - model_name: "gpt-oss-20b"
  #   litellm_params:
  #     model: "openai/openai/gpt-oss-20b"
  #     api_base: "http://<GPU_SERVER>:8000/v1"
  #     api_key: "none"
```

Полная инструкция: [Как добавить LLM-провайдера](docs/guides/add-provider.md)

### Шаг 3: Запуск платформы

```bash
docker compose up -d
```

Первый запуск занимает 3-5 минут (скачивание Docker images). Проверка:

```bash
# Статус всех контейнеров (должно быть 17 Up)
docker compose ps

# Health checks
curl http://localhost:8002/health          # SRE Agent
curl http://localhost:4000/health \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY"  # LiteLLM
curl http://localhost:8001/health          # Registry
curl http://localhost:8090/health          # Playground
curl http://localhost:3000/api/health      # Grafana
```

### Шаг 4: Индексация Runbooks

```bash
# Установить Python-зависимости (sentence-transformers, qdrant-client)
uv sync

# Проиндексировать Runbooks в Qdrant
uv run python agent/scripts/index_runbooks.py --runbooks-dir runbooks
# → "Indexed 20 chunks into Qdrant"
```

### Шаг 5: Проверка работы

```bash
# E2E demo (проверяет все сервисы, отправляет алерт, ждёт результат)
bash scripts/e2e_demo.sh

# Или отправить алерт вручную:
curl -X POST http://localhost:8002/webhooks/zabbix \
  -H "Content-Type: application/json" \
  -d '{
    "alert_id": "test-001",
    "host": "playground",
    "trigger": "CPU usage > 90%",
    "severity": "high",
    "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'",
    "description": "CPU utilization exceeded 90%"
  }'
```

Через 30-60 секунд отчёт придёт в Telegram.

---

## Архитектура

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐
│   Zabbix     │────>│  SRE Agent   │────>│   LiteLLM Proxy  │───> LLM Providers
│  (полигон)   │     │  (webhook +  │     │  (routing,       │     (OpenRouter,
│              │     │   SSH diag + │     │   guardrails,    │      vLLM, etc.)
│   Zabbix     │     │   Qdrant +   │     │   auth, metrics) │
│   Agent      │     │   Telegram)  │     └──────────────────┘
└──────┬───────┘     └──────┬───────┘              │
       │                    │ SSH                   │
┌──────▼───────┐     ┌──────▼───────┐     ┌────────▼─────────┐
│  Playground  │     │    Qdrant    │     │   Prometheus +   │
│  (test app + │     │  (Runbooks)  │     │   Grafana +      │
│   PG + Redis)│     │              │     │   Langfuse       │
└──────────────┘     └──────────────┘     └──────────────────┘
```

## Стек

| Компонент | Технология |
|---|---|
| Backend | Python 3.12+, FastAPI, Pydantic v2 |
| LLM Gateway | LiteLLM Proxy (routing, failover, auth, Prometheus, Langfuse) |
| Custom Guardrails | Prompt injection + secret leak detection (regex, CustomGuardrail) |
| Agent Core | Codex CLI (SSH диагностика через AGENTS.md) |
| Agent Protocol | A2A v1.0 (a2a-sdk) |
| Knowledge Base | Qdrant + intfloat/multilingual-e5-small |
| Monitoring (полигон) | Zabbix 7.x |
| Observability | Prometheus, Grafana, Langfuse |
| Database | PostgreSQL 16 |
| Deploy | Docker Compose (17 контейнеров) |
| Load Testing | Locust |
| Package Manager | uv |

## Сервисы и порты

| Сервис | URL | Credentials |
|---|---|---|
| SRE Agent | http://localhost:8002 | — |
| LiteLLM Gateway | http://localhost:4000 | `LITELLM_MASTER_KEY` из .env |
| Agent Registry | http://localhost:8001 | `REGISTRY_API_KEY` из .env |
| Grafana | http://localhost:3000 | admin / admin |
| Langfuse | http://localhost:3001 | admin@local.dev / admin1234 |
| Prometheus | http://localhost:9090 | — |
| Zabbix Web | http://localhost:8080 | Admin / zabbix |
| Playground | http://localhost:8090 | — |

## Сценарии использования

Подробное описание: [docs/guides/usage.md](docs/guides/usage.md)

| Сценарий | Как запустить |
|---|---|
| Автоматическая диагностика | Zabbix алерт или `curl POST /webhooks/zabbix` |
| Ручной тест | `curl -X POST http://localhost:8002/webhooks/zabbix -d '{"alert_id":"test","host":"playground","trigger":"CPU usage > 90%","severity":"high","timestamp":"...","description":"..."}'` |
| E2E demo | `bash scripts/e2e_demo.sh` |
| Нагрузочный тест Gateway | `uv run locust -f tests/load/locustfile.py LLMUser --host http://localhost:4000` |
| Стресс полигона | `docker compose exec playground-app bash /stress/cpu_stress.sh 60` |

## Локальная LLM на GPU (опционально)

Если у вас есть NVIDIA GPU с ≥24GB VRAM, можно развернуть gpt-oss-20b через vLLM:

```bash
docker compose -f vllm/docker-compose.vllm.yml up -d
```

Подробная инструкция: [docs/guides/deploy-vllm.md](docs/guides/deploy-vllm.md)

## Нагрузочное тестирование

```bash
# LLM Gateway: concurrent requests (Web UI на :8089)
uv run locust -f tests/load/locustfile.py LLMUser --host http://localhost:4000

# SRE Agent: multi-alert storm
uv run locust -f tests/load/locustfile.py AlertStormUser --host http://localhost:8002

# Headless mode (без UI)
uv run locust -f tests/load/locustfile.py LLMUser \
  --host http://localhost:4000 --headless -u 10 -r 2 -t 60s
```

## Документация

- [System Design](docs/system-design.md) — архитектурные решения, модули, workflow
- [Development Plan](docs/development-plan.md) — пошаговый план разработки
- [Diagrams](docs/diagrams/) — C4 Context, Container, Component, Workflow, Data Flow
- Спецификации: [LLM Gateway](docs/specs/llm-gateway.md) · [Agent Registry](docs/specs/agent-registry.md) · [SRE Agent](docs/specs/sre-agent.md) · [Observability](docs/specs/observability.md) · [Guardrails](docs/specs/guardrails.md) · [Auth](docs/specs/auth.md) · [Retriever](docs/specs/retriever.md) · [Serving & Config](docs/specs/serving-config.md) · [Load Testing](docs/specs/load-testing.md)
- [Product Proposal](docs/product-proposal.md) · [Governance & Risks](docs/governance.md)
- Руководства: [Добавить LLM-провайдера](docs/guides/add-provider.md) · [Добавить SSH-хост](docs/guides/add-ssh-host.md) · [Сценарии использования](docs/guides/usage.md) · [Развернуть vLLM на GPU](docs/guides/deploy-vllm.md)

## Что НЕ делает PoC

- **Write-operations:** Агент — read-only (нет перезапуска, kill, rm)
- **Human-in-the-loop:** Работает автономно от триггера до отчёта
- **PII masking:** Вынесено за рамки PoC
- **Бизнес-ошибки:** Только инфраструктурные инциденты
- **UI:** Только Telegram + Grafana
