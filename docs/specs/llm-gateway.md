# Спецификация: LLM API Gateway

## Назначение

Единая точка входа для всех LLM-запросов. Прокси между агентами и LLM-провайдерами с балансировкой, streaming, метриками, guardrails и авторизацией.

## API

### Chat Completions (основной endpoint)

```
POST /v1/chat/completions
Authorization: Bearer <agent-token>
Content-Type: application/json

{
  "model": "qwen-2.5-coder-7b",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "stream": true,
  "temperature": 0.7,
  "max_tokens": 4096
}
```

**Ответ (stream=true):** SSE stream, формат OpenAI:
```
data: {"id":"chatcmpl-...","choices":[{"delta":{"content":"Hello"},"index":0}]}

data: {"id":"chatcmpl-...","choices":[{"delta":{},"finish_reason":"stop","index":0}],"usage":{"prompt_tokens":50,"completion_tokens":100}}

data: [DONE]
```

**Ответ (stream=false):** Стандартный OpenAI Chat Completions response.

### Provider Management

```
POST   /providers          — регистрация провайдера
GET    /providers          — список провайдеров
GET    /providers/{id}     — детали провайдера
PUT    /providers/{id}     — обновление
DELETE /providers/{id}     — удаление
```

**Модель провайдера:**
```json
{
  "id": "uuid",
  "name": "vllm-local",
  "base_url": "http://vllm:8000/v1",
  "models": ["qwen-2.5-coder-7b", "qwen-2.5-coder-3b"],
  "api_key_encrypted": "...",
  "price_per_input_token": 0.0,
  "price_per_output_token": 0.0,
  "rate_limit_rpm": 100,
  "priority": 1,
  "weight": 10,
  "is_active": true
}
```

### Health

```
GET /health  →  {"status": "ok", "providers": {"vllm-local": "healthy", "openrouter": "degraded"}}
```

## Балансировка

### Стратегии (применяются последовательно)

1. **Model Match** — фильтрация провайдеров, поддерживающих запрошенную модель
2. **Health Filter** — исключение провайдеров в состоянии OPEN (circuit breaker)
3. **Strategy Selection** (configurable per model):
   - `round_robin` — циклический перебор
   - `weighted` — по статическим весам (`weight`)
   - `latency_based` — приоритет провайдеру с минимальным EMA latency
4. **Fallback** — если выбранный провайдер fails → retry со следующим

### Circuit Breaker

| Параметр | Значение по умолчанию |
|---|---|
| `failure_threshold` | 3 consecutive failures |
| `recovery_timeout` | 30s (первый probe) |
| `backoff_multiplier` | 2x (30s → 60s → 120s) |
| `max_recovery_timeout` | 300s |
| `probe_request` | GET /health к провайдеру |

**Состояния:**
- `CLOSED` — провайдер здоров, трафик идёт
- `OPEN` — провайдер исключён, probe по таймеру
- `HALF_OPEN` — probe отправлен, ждём результат; если OK → CLOSED, если FAIL → OPEN

### EMA Latency

```python
ema = alpha * current_latency + (1 - alpha) * prev_ema
# alpha = 0.3 (реакция на последние запросы)
```

## Streaming

- Gateway использует `httpx.AsyncClient` с `stream=True`
- SSE чанки проксируются по мере получения (не буферизуются)
- Метрики TTFT/TPOT собираются в реальном времени по таймингу чанков
- При разрыве соединения с провайдером → ошибка прокидывается клиенту (retry на уровне клиента)

## Метрики (OpenTelemetry)

| Метрика | Тип | Labels |
|---|---|---|
| `llm_gateway_requests_total` | Counter | provider, model, status_code |
| `llm_gateway_request_duration_seconds` | Histogram | provider, model |
| `llm_gateway_ttft_seconds` | Histogram | provider, model |
| `llm_gateway_tpot_seconds` | Histogram | provider, model |
| `llm_gateway_tokens_input_total` | Counter | provider, model |
| `llm_gateway_tokens_output_total` | Counter | provider, model |
| `llm_gateway_cost_dollars_total` | Counter | provider, model |
| `llm_gateway_provider_health` | Gauge | provider (0=open, 0.5=half_open, 1=closed) |
| `llm_gateway_active_streams` | Gauge | provider |
| `llm_gateway_guardrails_blocked_total` | Counter | rule |

## Ошибки

| Код | Когда | Тело |
|---|---|---|
| 400 | Невалидный запрос | `{"error": {"message": "...", "type": "invalid_request_error"}}` |
| 401 | Невалидный токен | `{"error": {"message": "...", "type": "authentication_error"}}` |
| 422 | Guardrails block | `{"error": {"message": "...", "type": "guardrails_error", "rule": "prompt_injection"}}` |
| 429 | Rate limit | `{"error": {"message": "...", "type": "rate_limit_error"}}` Retry-After header |
| 503 | Все провайдеры down | `{"error": {"message": "...", "type": "service_unavailable"}}` |
| 502 | Провайдер вернул ошибку (после всех retry) | `{"error": {"message": "...", "type": "upstream_error"}}` |

## Зависимости

- **PostgreSQL** — провайдеры, API keys
- **Prometheus** — scrape /metrics
- **Langfuse** — traces
- **LLM Providers** — upstream (vLLM, OpenRouter)
