# C4 Component Diagram — LLM API Gateway

Внутреннее устройство ядра системы — LLM API Gateway.

```mermaid
flowchart LR
    client(["Агент / Клиент<br/>POST /v1/chat/completions"])

    subgraph gateway ["LLM API Gateway"]
        direction LR

        api["<b>API Layer</b><br/>FastAPI Router<br/>Validation (Pydantic)"]
        auth["<b>Auth Middleware</b><br/>JWT / API-key<br/>валидация"]
        guardrails["<b>Guardrails</b><br/>Prompt injection<br/>Secret leak filter"]
        router["<b>Router / Balancer</b><br/>Model match →<br/>RR / Weighted / Latency"]
        cb["<b>Circuit Breaker</b><br/>CLOSED → OPEN →<br/>HALF-OPEN"]
        proxy["<b>Streaming Proxy</b><br/>httpx AsyncClient<br/>SSE pass-through"]
        metrics["<b>Metrics Collector</b><br/>OTel SDK<br/>TTFT, TPOT, tokens, cost"]

        api --> auth --> guardrails --> router
        router <--> cb
        router --> proxy
        proxy --> metrics
    end

    subgraph stores ["Хранение"]
        provider_store[("<b>Provider Store</b><br/>PostgreSQL + in-memory cache")]
        auth_store[("<b>Auth Store</b><br/>PostgreSQL + in-memory cache")]
    end

    llm[/"<b>LLM Provider</b><br/>vLLM / OpenRouter"/]
    prometheus["<b>Prometheus</b>"]
    langfuse["<b>Langfuse</b>"]

    client --> api
    proxy -- "HTTP SSE stream" --> llm
    llm -- "SSE response" --> proxy

    auth -. "Валидация токена" .-> auth_store
    router -. "Список провайдеров" .-> provider_store

    metrics -. "/metrics" .-> prometheus
    metrics -. "Trace spans" .-> langfuse

    classDef middleware fill:#1168bd,color:#fff,stroke:none
    classDef store fill:#438dd5,color:#fff,stroke:none
    classDef external fill:#999,color:#fff,stroke:none

    class api,auth,guardrails,router,cb,proxy,metrics middleware
    class provider_store,auth_store store
    class llm,prometheus,langfuse external
```

## Пайплайн обработки запроса

```
Request → API Layer → Auth → Guardrails → Router ←→ Circuit Breaker
                                            │
                                            ↓
                                      Streaming Proxy → LLM Provider
                                            │
                                      Metrics Collector → Prometheus / Langfuse
```

## Компоненты

| Компонент | Ответственность | Stateful? |
|---|---|---|
| API Layer | HTTP routing, validation (Pydantic) | Нет |
| Auth Middleware | JWT decode / API-key lookup | Нет (читает из Auth Store) |
| Guardrails | Regex + LLM classifier, блокировка | Нет |
| Router / Balancer | Выбор провайдера по стратегии | Да (EMA latency в памяти) |
| Circuit Breaker | Tracking health state провайдеров | Да (state в памяти) |
| Streaming Proxy | httpx SSE pass-through | Нет |
| Metrics Collector | Counters, histograms, traces | Да (OTel SDK буфер) |
| Provider Store | Кэш + PostgreSQL sync | Да (in-memory cache, TTL 30s) |
| Auth Store | Кэш + PostgreSQL | Да (in-memory cache) |
