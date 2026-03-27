# Data Flow Diagram — AI-SRE Platform

Как данные проходят через систему: что передаётся, что хранится, что логируется. Разделено на два аспекта для читаемости.

## Основной data path (запрос → обработка → результат)

```mermaid
flowchart LR
    subgraph input ["Входные данные"]
        ALERT["Zabbix Alert<br/>(JSON)"]
        RUNBOOKS["Runbooks<br/>(.md файлы)"]
        CFG["Конфигурация<br/>провайдеров"]
    end

    subgraph processing ["Обработка"]
        WH["Webhook<br/>Handler"]
        CODEX["Codex CLI"]
        GW["LiteLLM Proxy"]
    end

    subgraph llm ["LLM-провайдеры"]
        VLLM["vLLM"]
        OR["OpenRouter"]
    end

    subgraph storage ["Хранение"]
        PG[("PostgreSQL")]
        QD[("Qdrant")]
    end

    TG["Telegram"]

    ALERT --> WH
    WH -- "Промпт" --> CODEX
    CODEX -- "Chat Completions" --> GW
    GW --> VLLM
    GW --> OR
    VLLM -- "SSE tokens" --> GW
    OR -- "SSE tokens" --> GW
    GW -- "SSE stream" --> CODEX
    CODEX -- "Vector search" --> QD
    QD -- "Runbook chunks" --> CODEX
    CODEX -- "Отчёт" --> TG

    RUNBOOKS -- "Embedding pipeline" --> QD
    CFG -- "Admin API" --> PG
    GW -. "Read config" .-> PG
```

## Observability data path (метрики, логи, трейсы)

```mermaid
flowchart LR
    subgraph sources ["Источники данных"]
        GW2["LiteLLM Proxy"]
        AGENT2["SRE Agent"]
    end

    subgraph collect ["Сбор"]
        OTEL["OTel SDK<br/>(встроен в Gateway/Agent)"]
    end

    subgraph store_obs ["Хранение"]
        PROM[("Prometheus<br/>retention: 30d")]
        LF[("Langfuse<br/>retention: 14d")]
    end

    subgraph visualize ["Визуализация"]
        GRAFANA["Grafana<br/>Дашборды"]
        LF_UI["Langfuse UI<br/>Traces"]
    end

    GW2 -- "RPS, latency, TTFT,<br/>TPOT, tokens, cost" --> OTEL
    AGENT2 -- "Investigations,<br/>shell commands" --> OTEL
    OTEL -- "Metrics" --> PROM
    OTEL -- "Traces" --> LF
    PROM --> GRAFANA
    LF --> LF_UI

    GW2 -. "stdout: JSON logs" .-> STDOUT["Container logs"]
    AGENT2 -. "stdout: JSON logs" .-> STDOUT
```

## Классификация данных

### Что передаётся (транзитно)

| Данные | Откуда | Куда | Формат |
|---|---|---|---|
| Zabbix alert | Zabbix | Webhook Handler | JSON |
| LLM prompt (messages) | Codex | Gateway → Provider | OpenAI Chat Completions JSON |
| LLM response (tokens) | Provider | Gateway → Codex | SSE (data: JSON chunks) |
| Shell stdout/stderr | Полигон | Codex context | Plain text (truncated 4000 chars) |
| Runbook chunks | Qdrant | Codex context | Plain text |
| Incident report | Codex | Telegram | Markdown |

### Что хранится (persistent)

| Данные | Где | Retention | Формат |
|---|---|---|---|
| LLM deployments, virtual keys, spend | PostgreSQL (LiteLLM DB) | Permanent | Prisma |
| Agent Cards | PostgreSQL (Registry DB) | Permanent | JSONB (A2A spec) |
| Runbook embeddings | Qdrant | Permanent | Vectors + metadata |
| Time-series metrics | Prometheus | 30 дней | TSDB |
| LLM traces | Langfuse | 14 дней | Spans, events |

### Что логируется

| Что | Куда | Зачем |
|---|---|---|
| LLM-запросы: prompt, completion, model, tokens, latency, cost | Langfuse | Трейсинг, cost tracking |
| Tool calls: команда, stdout, duration | Langfuse | Анализ поведения агента |
| RPS, latency p50/p95, TTFT, TPOT, error rate | Prometheus → Grafana | Операционный мониторинг |
| Cooldown state changes | Prometheus + stdout | Alerting |
| Guardrails срабатывания | Langfuse + stdout | Security audit |
| Auth failures | stdout (JSON) | Security audit |
