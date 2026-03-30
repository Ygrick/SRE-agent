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

## Quick Start

```bash
# 1. Склонировать и настроить
git clone <repo-url> && cd sre-agent
cp .env.example .env
# Отредактировать .env — подставить API ключи провайдеров

# 2. Запустить всё
docker compose up -d

# 3. Проиндексировать Runbooks в Qdrant
uv sync
uv run python agent/scripts/index_runbooks.py --runbooks-dir runbooks

# 4. Запустить E2E demo
bash scripts/e2e_demo.sh
```

## Архитектура

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐
│   Zabbix     │────>│  SRE Agent   │────>│   LiteLLM Proxy  │───> LLM Providers
│  (полигон)   │     │  (webhook +  │     │  (routing,       │     (OpenRouter,
│              │     │   SSH diag + │     │   guardrails,    │      RMR Router)
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
| Agent Core | Codex CLI + fallback SSH диагностика |
| Agent Protocol | A2A v1.0 (a2a-sdk) |
| Knowledge Base | Qdrant + intfloat/multilingual-e5-small |
| Monitoring (полигон) | Zabbix 7.x |
| Observability | Prometheus, Grafana, Langfuse |
| Database | PostgreSQL 16 |
| Deploy | Docker Compose (14 контейнеров) |
| Load Testing | Locust |
| Package Manager | uv |

## Сервисы и порты

| Сервис | URL | Назначение |
|---|---|---|
| LiteLLM Gateway | http://localhost:4000 | LLM прокси |
| SRE Agent | http://localhost:8002 | Webhook + API |
| Agent Registry | http://localhost:8001 | A2A реестр |
| Grafana | http://localhost:3000 | Дашборды (admin/admin) |
| Langfuse | http://localhost:3001 | LLM трейсы |
| Prometheus | http://localhost:9090 | Метрики |
| Zabbix Web | http://localhost:8080 | Мониторинг полигона (Admin/zabbix) |
| Playground | http://localhost:8090 | Тестовый сервис |

## API

```bash
# Отправить алерт вручную
curl -X POST http://localhost:8002/webhooks/zabbix \
  -H "Content-Type: application/json" \
  -d '{"alert_id":"manual-1","host":"playground","trigger":"CPU usage > 90%","severity":"high","timestamp":"2026-03-30T10:00:00Z","description":"CPU high"}'

# Список зарегистрированных агентов
curl http://localhost:8001/agents -H "Authorization: Bearer changeme-registry-key"

# LLM запрос через Gateway
curl -X POST http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-master-changeme" \
  -d '{"model":"gpt-oss-120b","messages":[{"role":"user","content":"Hello"}]}'
```

## Нагрузочное тестирование

```bash
# LLM Gateway: concurrent requests
uv run locust -f tests/load/locustfile.py LLMUser --host http://localhost:4000

# SRE Agent: multi-alert storm
uv run locust -f tests/load/locustfile.py AlertStormUser --host http://localhost:8002
```

Web UI: http://localhost:8089

## Документация

- [System Design](docs/system-design.md) — архитектурные решения, модули, workflow
- [Development Plan](docs/development-plan.md) — пошаговый план разработки
- [Diagrams](docs/diagrams/) — C4 Context, Container, Component, Workflow, Data Flow
- Спецификации: [LLM Gateway](docs/specs/llm-gateway.md) · [Agent Registry](docs/specs/agent-registry.md) · [SRE Agent](docs/specs/sre-agent.md) · [Observability](docs/specs/observability.md) · [Guardrails](docs/specs/guardrails.md) · [Auth](docs/specs/auth.md) · [Retriever](docs/specs/retriever.md) · [Serving & Config](docs/specs/serving-config.md) · [Load Testing](docs/specs/load-testing.md)
- [Product Proposal](docs/product-proposal.md) · [Governance & Risks](docs/governance.md)
- [Как добавить LLM-провайдера](docs/guides/add-provider.md)

## Что НЕ делает PoC

- **Write-operations:** Агент — read-only (нет перезапуска, kill, rm)
- **Human-in-the-loop:** Работает автономно от триггера до отчёта
- **PII masking:** Вынесено за рамки PoC
- **Бизнес-ошибки:** Только инфраструктурные инциденты
- **UI:** Только Telegram + Grafana
