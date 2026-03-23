# C4 Container Diagram — AI-SRE Platform

Внутренняя структура платформы: контейнеры, их роли и связи.

```mermaid
flowchart TB
    sre_engineer["<b>L2 SRE-инженер</b>"]
    platform_admin["<b>Platform Admin</b>"]

    subgraph platform ["AI-SRE Platform"]
        direction TB

        subgraph core ["Ядро"]
            gateway["<b>LLM API Gateway</b><br/>FastAPI · httpx<br/>Routing, балансировка,<br/>streaming, guardrails, auth"]
            registry["<b>A2A Agent Registry</b><br/>FastAPI · a2a-sdk<br/>CRUD Agent Cards"]
            sre_agent["<b>SRE Agent</b><br/>FastAPI + Codex CLI<br/>Webhook handler,<br/>shell диагностика,<br/>MCP tools"]
        end

        subgraph data ["Хранение"]
            postgres[("<b>PostgreSQL 16</b><br/>Провайдеры, Agent Cards,<br/>API keys")]
            qdrant[("<b>Qdrant</b><br/>Runbook embeddings")]
        end

        subgraph observability ["Наблюдаемость"]
            prometheus["<b>Prometheus</b><br/>Time-series метрики"]
            grafana["<b>Grafana</b><br/>Дашборды"]
            langfuse["<b>Langfuse</b><br/>LLM трейсинг"]
        end

        subgraph playground_env ["Полигон"]
            playground_app["<b>Playground App</b><br/>Тестовый сервис"]
            zabbix["<b>Zabbix</b><br/>Мониторинг полигона"]
        end
    end

    vllm[/"<b>vLLM</b><br/>Локальный LLM"/]
    openrouter[/"<b>OpenRouter</b><br/>Облачный LLM"/]
    telegram["<b>Telegram</b><br/>Отчёты"]

    %% Основной data path
    zabbix -- "Webhook: алерт" --> sre_agent
    sre_agent -- "LLM-запросы (SSE)" --> gateway
    gateway -- "Проксирование (SSE)" --> vllm
    gateway -- "Проксирование (SSE)" --> openrouter
    sre_agent -- "Read-only команды" --> playground_app
    sre_agent -- "Поиск Runbooks" --> qdrant
    sre_agent -- "Отчёт" --> telegram

    %% Registry
    sre_agent -. "Регистрация (A2A)" .-> registry

    %% Хранение
    gateway --> postgres
    registry --> postgres

    %% Observability (направление стрелок = направление данных/запросов)
    prometheus -- "Scrape /metrics" --> gateway
    prometheus -- "Scrape /metrics" --> sre_agent
    grafana -- "PromQL запросы" --> prometheus
    gateway -. "Traces" .-> langfuse
    sre_agent -. "Traces" .-> langfuse

    %% Мониторинг полигона
    zabbix -. "Zabbix Agent" .-> playground_app

    %% Пользователи
    platform_admin --> grafana
    platform_admin --> gateway
    platform_admin --> registry
    sre_engineer -. "Читает отчёты" .-> telegram

    classDef person fill:#08427b,color:#fff,stroke:none
    classDef core_svc fill:#1168bd,color:#fff,stroke:none
    classDef storage fill:#438dd5,color:#fff,stroke:none
    classDef obs fill:#2d882d,color:#fff,stroke:none
    classDef external fill:#999,color:#fff,stroke:none
    classDef playground fill:#d4a017,color:#fff,stroke:none

    class sre_engineer,platform_admin person
    class gateway,registry,sre_agent core_svc
    class postgres,qdrant storage
    class prometheus,grafana,langfuse obs
    class vllm,openrouter,telegram external
    class playground_app,zabbix playground
```

## Контейнеры и порты

| Контейнер | Технология | Порт | Цвет на диаграмме |
|---|---|---|---|
| `llm-gateway` | Python 3.12, FastAPI, httpx | 8000 | Синий (core) |
| `agent-registry` | Python 3.12, FastAPI, a2a-sdk | 8001 | Синий (core) |
| `sre-agent` | Python 3.12, FastAPI + Codex CLI | 8002 | Синий (core) |
| `postgres` | PostgreSQL 16 | 5432 | Голубой (storage) |
| `qdrant` | Qdrant | 6333 | Голубой (storage) |
| `prometheus` | Prometheus | 9090 | Зелёный (observability) |
| `grafana` | Grafana | 3000 | Зелёный (observability) |
| `langfuse` | Langfuse (self-hosted) | 3001 | Зелёный (observability) |
| `zabbix-server` + `zabbix-web` | Zabbix | 10051 / 8080 | Жёлтый (полигон) |
| `playground-app` | Python/Java | 8090 | Жёлтый (полигон) |
