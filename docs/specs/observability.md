# Спецификация: Observability

## Назначение

Сбор, хранение и визуализация метрик, логов и трейсов. Два контура:
1. **Платформа** — LiteLLM Prometheus + Grafana + Langfuse
2. **Полигон** — Zabbix (мониторинг тестового сервиса, триггеры для SRE-агента)

## Компоненты

### LiteLLM Prometheus Metrics

LiteLLM экспортирует метрики через `success_callback: ["prometheus"]`.

**Метрики Gateway:**

| Метрика | Тип | Что измеряет |
|---|---|---|
| `litellm_proxy_total_requests_metric` | Counter | RPS по моделям и статусам |
| `litellm_request_total_latency_metric` | Histogram | E2E latency запроса (p50/p95/p99) |
| `litellm_llm_api_time_to_first_token_metric` | Histogram | TTFT |
| `litellm_input_tokens_metric` | Counter | Input tokens |
| `litellm_output_tokens_metric` | Counter | Output tokens |
| `litellm_spend_metric` | Counter | Cost ($) |
| `litellm_proxy_failed_requests_metric` | Counter | Error rate |
| `litellm_deployment_failure_responses` | Counter | Failures per deployment |
| `litellm_remaining_team_budget_metric` | Gauge | Остаток бюджета |

**Метрики SRE-агента (наш код, OTel SDK):**

| Метрика | Тип | Что измеряет |
|---|---|---|
| `sre_agent_investigations_total` | Counter | Расследования по severity и status |
| `sre_agent_investigation_duration_seconds` | Histogram | Длительность расследования |
| `sre_agent_shell_commands_total` | Counter | Shell-команды по типам |

Экспорт метрик агента: `opentelemetry-exporter-prometheus` → endpoint `/metrics` на порту 8002.

**TPOT gap:** TPOT (time per output token) доступен только через OpenTelemetry, не через Prometheus callback LiteLLM. Решение: добавить `CustomLogger` callback (~30 строк), который считает TPOT из streaming chunks и экспортирует в Prometheus.

### Prometheus

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'litellm'
    static_configs:
      - targets: ['litellm:4000']
    metrics_path: /metrics

  - job_name: 'sre-agent'
    static_configs:
      - targets: ['sre-agent:8002']
    metrics_path: /metrics
```

**Retention:** 30 дней.

### Grafana

**Дашборды:**

#### 1. LLM Gateway Overview
- RPS по моделям и deployments (stacked bar)
- Latency p50/p95/p99 (time series)
- Error rate per deployment (time series)
- Provider health / cooldown status
- Spend per hour/day (stacked by deployment)

#### 2. LLM Metrics
- TTFT distribution (histogram heatmap)
- Tokens in/out per minute (time series)
- Cost per investigation (bar chart)
- Budget remaining (gauge)

#### 3. SRE Agent
- Investigations per hour (time series)
- Investigation duration p50/p95 (time series)
- Shell commands per investigation (bar chart)
- Success / failure rate (pie chart)

#### 4. System Health
- CPU / Memory usage per container (time series, from cAdvisor or node-exporter)
- Alerting rules triggered (log panel)

**Alerting rules (Grafana Alerting):**
- All LLM deployments in cooldown > 1 min → Critical
- Gateway error rate > 10% for 5 min → Warning
- Investigation timeout rate > 50% → Warning
- TTFT p95 > 5s → Warning

### Langfuse

Два уровня трейсинга:

**Уровень A — Gateway-level (LiteLLM native integration):**
- `success_callback: ["langfuse"]` в config
- LiteLLM автоматически записывает trace каждого LLM-запроса
- Атрибуты: model, provider, tokens_in, tokens_out, cost, latency, TTFT, status
- Per-team Langfuse routing через `default_team_settings` (если нужно)

**Уровень B — Agent-level (парсинг `codex exec --json`):**
- Webhook handler запускает `codex exec --json` и парсит structured event stream из stdout
- Parent trace: `investigation` (alert_id, host, severity, duration)
- Child spans:
  - `llm_call` — каждый вызов LLM
  - `shell_command` — command, exit_code, stdout (truncated), duration
  - `tool_call` — qdrant_search / telegram_send: input, output, duration

**Retention:** 14 дней (configurable).

**Self-hosted:** Docker container с отдельной PostgreSQL (не основная БД).

## Zabbix (мониторинг полигона)

### Что мониторит

| Метрика | Триггер | Severity |
|---|---|---|
| CPU usage | > 90% for 5 min | High |
| Memory usage | > 85% for 5 min | High |
| Disk usage | > 95% | Disaster |
| Process count | > 500 | Warning |
| Container status | Container down | High |
| HTTP endpoint | Response time > 5s or status != 200 | Average |

### Webhook

Формат payload и обработка: [sre-agent.md](sre-agent.md#webhook-handler)

## Structured Logging

**Для наших сервисов (Agent, Registry):** `structlog` — structured JSON logging.

```python
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
)
```

**Для LiteLLM:** встроенное логирование, конфигурируется через `set_verbose` и log level.

Корреляция: `trace_id` в логах совпадает с trace_id в Langfuse, что позволяет переходить из Grafana Logs → Langfuse Trace.
