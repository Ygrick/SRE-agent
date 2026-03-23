# Спецификация: Observability

## Назначение

Сбор, хранение и визуализация метрик, логов и трейсов всей платформы. Два контура:
1. **Платформа** — OpenTelemetry → Prometheus → Grafana + Langfuse
2. **Полигон** — Zabbix (мониторинг тестового сервиса, триггеры для SRE-агента)

## Компоненты

### OpenTelemetry SDK

Встроен в Gateway и Webhook Handler.

**Traces:**
- Каждый LLM-запрос → span с атрибутами: provider, model, status, latency, tokens
- Каждый agent step → span: tool call, shell command, qdrant search
- Parent-child: investigation → LLM calls → tool calls

**Metrics (export в Prometheus формате):**

| Метрика | Тип | Labels | Источник |
|---|---|---|---|
| `llm_gateway_requests_total` | Counter | provider, model, status_code | Gateway |
| `llm_gateway_request_duration_seconds` | Histogram (buckets: 0.1, 0.5, 1, 2, 5, 10, 30) | provider, model | Gateway |
| `llm_gateway_ttft_seconds` | Histogram (buckets: 0.05, 0.1, 0.5, 1, 2, 5) | provider, model | Gateway |
| `llm_gateway_tpot_seconds` | Histogram (buckets: 0.01, 0.02, 0.05, 0.1, 0.2) | provider, model | Gateway |
| `llm_gateway_tokens_input_total` | Counter | provider, model | Gateway |
| `llm_gateway_tokens_output_total` | Counter | provider, model | Gateway |
| `llm_gateway_cost_dollars_total` | Counter | provider, model | Gateway |
| `llm_gateway_provider_health` | Gauge | provider | Gateway |
| `llm_gateway_active_streams` | Gauge | provider | Gateway |
| `llm_gateway_guardrails_blocked_total` | Counter | rule | Gateway |
| `sre_agent_investigations_total` | Counter | severity, status | Agent |
| `sre_agent_investigation_duration_seconds` | Histogram | severity | Agent |
| `sre_agent_shell_commands_total` | Counter | command_type | Agent |

### Prometheus

**Конфигурация:**
```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'llm-gateway'
    static_configs:
      - targets: ['llm-gateway:8000']
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
- RPS по провайдерам (stacked bar)
- Latency p50/p95/p99 по провайдерам (time series)
- Error rate по провайдерам (time series)
- Active streams (gauge)
- Provider health status (stat panels: green/yellow/red)

#### 2. LLM Metrics
- TTFT distribution по провайдерам (histogram heatmap)
- TPOT distribution по провайдерам (histogram heatmap)
- Tokens in/out per minute (time series)
- Cost per hour/day (time series, stacked by provider)
- Cost per investigation (bar chart)

#### 3. SRE Agent
- Investigations per hour (time series)
- Investigation duration p50/p95 (time series)
- Shell commands per investigation (bar chart)
- Success / failure rate (pie chart)
- Guardrails blocks (time series)

#### 4. System Health
- CPU / Memory usage per container (time series)
- Circuit breaker state changes (annotations)
- Alerting rules triggered (log panel)

**Alerting rules (Grafana Alerting):**
- All LLM providers unhealthy > 1 min → Critical
- Gateway error rate > 10% for 5 min → Warning
- Investigation timeout rate > 50% → Warning
- TTFT p95 > 5s → Warning

### Langfuse

**Интеграция:**
- Gateway: `langfuse.trace()` на каждый LLM-запрос
- Agent: `langfuse.trace()` на каждое расследование (parent trace), LLM calls и tool calls как child spans
- Атрибуты: model, provider, tokens, cost, latency, status, investigation_id

**Retention:** 14 дней (configurable).

**Self-hosted:** Docker container с PostgreSQL (отдельная БД от основной).

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

```
Action: Send to URL
URL: http://sre-agent:8002/webhooks/zabbix
Method: POST
Content-Type: application/json
Body:
{
  "alert_id": "{EVENT.ID}",
  "host": "{HOST.NAME}",
  "trigger": "{TRIGGER.NAME}",
  "severity": "{TRIGGER.SEVERITY}",
  "timestamp": "{EVENT.DATE} {EVENT.TIME}",
  "description": "{TRIGGER.DESCRIPTION}"
}
```

## Structured Logging

Все сервисы логируют в stdout в формате JSON:

```json
{
  "timestamp": "2026-03-23T10:15:00.123Z",
  "level": "INFO",
  "service": "llm-gateway",
  "trace_id": "abc123",
  "span_id": "def456",
  "message": "LLM request completed",
  "provider": "vllm-local",
  "model": "qwen-2.5-coder-7b",
  "latency_ms": 1234,
  "tokens_in": 500,
  "tokens_out": 200,
  "status": 200
}
```
