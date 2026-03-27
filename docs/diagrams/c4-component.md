# C4 Component Diagram — LLM API Gateway (LiteLLM Proxy)

Внутреннее устройство LiteLLM Proxy с нашими кастомными guardrails.

```mermaid
flowchart LR
    client(["Агент / Клиент<br/>POST /v1/chat/completions"])

    subgraph litellm ["LiteLLM Proxy"]
        direction LR

        api["<b>API Layer</b><br/>FastAPI<br/>OpenAI-compatible"]
        auth["<b>Auth</b><br/>Virtual Keys<br/>Budget / Rate limits"]
        guardrails["<b>CustomGuardrails</b><br/>Prompt injection (regex)<br/>Secret leak (regex)"]
        router["<b>Router</b><br/>Latency-based /<br/>Weighted / Least-busy"]
        cooldown["<b>Cooldown Manager</b><br/>allowed_fails → cooldown<br/>→ recovery"]
        proxy["<b>Streaming Proxy</b><br/>SSE pass-through"]
        callbacks["<b>Callbacks</b><br/>Prometheus metrics<br/>Langfuse traces"]

        api --> auth --> guardrails --> router
        router <--> cooldown
        router --> proxy
        proxy --> callbacks
    end

    subgraph stores ["Хранение (LiteLLM DB)"]
        litellm_db[("<b>PostgreSQL</b><br/>Virtual keys, spend,<br/>model config")]
    end

    llm[/"<b>LLM Provider</b><br/>vLLM / OpenRouter"/]
    prometheus["<b>Prometheus</b>"]
    langfuse["<b>Langfuse</b>"]

    client --> api
    proxy -- "HTTP SSE stream" --> llm
    llm -- "SSE response" --> proxy

    auth -. "Keys, budgets" .-> litellm_db
    router -. "Model config" .-> litellm_db

    callbacks -. "/metrics" .-> prometheus
    callbacks -. "Trace spans" .-> langfuse

    classDef litellm_built_in fill:#1168bd,color:#fff,stroke:none
    classDef custom fill:#e74c3c,color:#fff,stroke:none
    classDef store fill:#438dd5,color:#fff,stroke:none
    classDef external fill:#999,color:#fff,stroke:none

    class api,auth,router,cooldown,proxy,callbacks litellm_built_in
    class guardrails custom
    class litellm_db store
    class llm,prometheus,langfuse external
```

**Легенда:** Синий = LiteLLM built-in, Красный = наш кастомный код, Серый = внешние сервисы.

## Пайплайн обработки запроса

```
Request → API Layer → Auth (virtual key) → CustomGuardrails → Router ←→ Cooldown Manager
                                                                 │
                                                                 ↓
                                                          Streaming Proxy → LLM Provider
                                                                 │
                                                          Callbacks → Prometheus / Langfuse
```

## Что LiteLLM built-in vs наш код

| Компонент | LiteLLM built-in | Наш код |
|---|---|---|
| API Layer (OpenAI-compatible) | Да | — |
| Auth (virtual keys, budgets, rate limits) | Да | — |
| **Guardrails** (prompt injection, secret leak) | — | **`custom_guardrail.py`** |
| Router (latency-based, weighted, etc.) | Да | — |
| Cooldown / Failover | Да | — |
| Streaming Proxy | Да | — |
| Prometheus metrics | Да (callback) | — |
| Langfuse traces | Да (callback) | — |
| TPOT metric | — | **CustomLogger callback** (опционально) |
