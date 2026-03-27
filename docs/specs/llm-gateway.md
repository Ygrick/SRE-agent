# Спецификация: LLM API Gateway (LiteLLM Proxy)

## Назначение

Единая точка входа для всех LLM-запросов. Используем [LiteLLM Proxy](https://github.com/BerriAI/litellm) — production-ready OpenAI-compatible прокси с routing, failover, метриками и cost tracking из коробки.

**Почему LiteLLM, а не custom Gateway:**
- Покрывает 90%+ требований: routing, circuit breaker, streaming, auth, Prometheus, Langfuse, cost tracking
- MIT-лицензия, self-hosted Docker, активно поддерживается
- OpenAI-compatible API — Codex подключается как к обычному OpenAI endpoint
- Кастомные guardrails через `CustomGuardrail` base class — не нужно форкать

## API

Стандартный OpenAI-compatible API, предоставляемый LiteLLM:

```
POST /v1/chat/completions     — Chat Completions (stream + non-stream)
POST /v1/embeddings           — Embeddings
GET  /v1/models               — Список доступных моделей
GET  /health                  — Health check
POST /model/new               — Добавить deployment (dynamic)
POST /model/update            — Обновить deployment
POST /model/delete            — Удалить deployment
GET  /model/info              — Информация о моделях
POST /key/generate            — Создать virtual key
GET  /key/info                — Информация о ключе
POST /key/delete              — Удалить ключ
```

## Конфигурация (`config.yaml`)

```yaml
model_list:
  # --- vLLM (локальный) ---
  - model_name: "qwen-2.5-coder-7b"
    litellm_params:
      model: "openai/qwen-2.5-coder-7b"
      api_base: "http://vllm:8000/v1"
      api_key: "os.environ/VLLM_API_KEY"
      input_cost_per_token: 0.0
      output_cost_per_token: 0.0
    model_info:
      id: "vllm-qwen-7b"

  # --- OpenRouter (облачный, fallback) ---
  - model_name: "qwen-2.5-coder-7b"
    litellm_params:
      model: "openrouter/qwen/qwen-2.5-coder-7b-instruct"
      api_key: "os.environ/OPENROUTER_API_KEY"
      # Цены OpenRouter (пример)
      input_cost_per_token: 0.00000015
      output_cost_per_token: 0.00000015
    model_info:
      id: "openrouter-qwen-7b"

router_settings:
  routing_strategy: "latency-based-routing"
  # Circuit breaker / Cooldown
  allowed_fails: 3
  cooldown_time: 30              # секунд в cooldown после failure threshold
  retry_after: 15                # секунд между retries
  num_retries: 2                 # retries перед failover
  timeout: 60                    # таймаут запроса к провайдеру
  # Health checks
  enable_pre_call_checks: true   # проверка перед routing

litellm_settings:
  drop_params: true              # игнорировать неподдерживаемые параметры
  set_verbose: false
  # Callbacks
  success_callback: ["prometheus", "langfuse"]
  failure_callback: ["prometheus", "langfuse"]

general_settings:
  master_key: "os.environ/LITELLM_MASTER_KEY"
  database_url: "os.environ/LITELLM_DATABASE_URL"
  store_model_in_db: true        # dynamic model CRUD
  # Guardrails
  guardrails:
    - guardrail_name: "sre-prompt-injection"
      litellm_params:
        guardrail: "custom_guardrail.PromptInjectionGuardrail"
        mode: "pre_call"
    - guardrail_name: "sre-secret-leak"
      litellm_params:
        guardrail: "custom_guardrail.SecretLeakGuardrail"
        mode: "pre_call"
```

## Балансировка

### Стратегии (встроенные в LiteLLM Router)

| Стратегия | Описание | Наш выбор |
|---|---|---|
| `latency-based-routing` | Приоритет deployment-у с минимальной latency | **Да (primary)** |
| `simple-shuffle` | Случайный выбор с учётом weight | Для A/B тестов |
| `usage-based-routing-v2` | По utilization (RPM/TPM) | Альтернатива |
| `least-busy` | Наименьшее количество активных запросов | Альтернатива |
| `cost-based-routing` | Приоритет дешёвому | Для экономии |

### Circuit Breaker / Cooldown

LiteLLM реализует cooldown-механизм:

1. Deployment получает `allowed_fails` (default: 3) consecutive failures
2. Deployment переходит в **cooldown** на `cooldown_time` секунд
3. Трафик маршрутизируется на оставшиеся deployments
4. После cooldown — deployment возвращается в пул
5. Background health checks (`enable_pre_call_checks`) проверяют доступность

**Параметры:**

| Параметр | Default | Наше значение |
|---|---|---|
| `allowed_fails` | 3 | 3 |
| `cooldown_time` | 30s | 30s |
| `num_retries` | 2 | 2 |
| `timeout` | 600s | 60s |

## Streaming

- LiteLLM проксирует SSE чанки по мере получения (FastAPI `StreamingResponse`)
- `stream_timeout` configurable per deployment
- При разрыве соединения — ошибка прокидывается клиенту

## Метрики

LiteLLM экспортирует Prometheus метрики через `success_callback: ["prometheus"]`:

| Метрика | Тип |
|---|---|
| `litellm_proxy_total_requests_metric` | Counter |
| `litellm_request_total_latency_metric` | Histogram |
| `litellm_llm_api_time_to_first_token_metric` | Histogram |
| `litellm_input_tokens_metric` | Counter |
| `litellm_output_tokens_metric` | Counter |
| `litellm_spend_metric` | Counter |
| `litellm_proxy_failed_requests_metric` | Counter |
| `litellm_deployment_failure_responses` | Counter |
| `litellm_remaining_team_budget_metric` | Gauge |

**TPOT gap:** TPOT доступен только через OpenTelemetry (`gen_ai.client.response.time_per_output_token`). При необходимости — решаем через OTel Collector → Prometheus или кастомный callback.

Полная конфигурация Prometheus + Grafana дашборды: [observability.md](observability.md)

## Ошибки

LiteLLM возвращает ошибки в формате OpenAI:

| Код | Когда |
|---|---|
| 400 | Невалидный запрос |
| 401 | Невалидный ключ / master key |
| 422 | Guardrail block |
| 429 | Rate limit / budget exceeded |
| 503 | Все deployments в cooldown |

## Зависимости

- **PostgreSQL** — virtual keys, spend tracking, model store (LiteLLM Prisma DB)
- **Prometheus** — scrape /metrics
- **Langfuse** — traces (per LLM-request, native integration)
- **LLM Providers** — upstream (vLLM, OpenRouter)
