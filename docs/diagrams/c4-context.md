# C4 Context Diagram — AI-SRE Platform

Система, пользователи, внешние сервисы и границы.

```mermaid
flowchart TB
    sre_engineer["<b>L2 SRE-инженер</b><br/>Получает отчёты,<br/>принимает решения"]
    platform_admin["<b>Platform Admin</b><br/>Настраивает провайдеров,<br/>агентов, дашборды"]

    subgraph platform ["AI-SRE Platform"]
        direction TB
        ai_sre["<b>AI-SRE Platform</b><br/>LiteLLM Proxy · Agent Registry<br/>SRE-агент · Observability"]
    end

    vllm[/"<b>vLLM</b><br/>Локальный LLM-сервер"/]
    openrouter[/"<b>OpenRouter API</b><br/>Облачный LLM-провайдер"/]
    playground[("<b>Полигон</b><br/>App + PostgreSQL + Redis")]
    zabbix["<b>Zabbix</b><br/>Мониторинг полигона"]
    qdrant[("<b>Qdrant</b><br/>Векторная БД Runbooks")]
    telegram["<b>Telegram Bot API</b><br/>Доставка отчётов"]

    zabbix -- "Webhook: алерт<br/>(HTTP POST)" --> ai_sre
    ai_sre -- "LLM-запросы<br/>(HTTP SSE)" --> vllm
    ai_sre -- "LLM-запросы<br/>(HTTP SSE)" --> openrouter
    ai_sre -- "Read-only диагностика<br/>(shell)" --> playground
    ai_sre -- "Поиск Runbooks<br/>(HTTP)" --> qdrant
    ai_sre -- "Отчёт об инциденте<br/>(HTTP POST)" --> telegram
    zabbix -. "Мониторинг<br/>(Zabbix Agent)" .-> playground
    sre_engineer -. "Читает отчёты" .-> telegram
    platform_admin -- "Конфигурация<br/>(HTTP API + Grafana)" --> ai_sre

    classDef person fill:#08427b,color:#fff,stroke:none
    classDef system fill:#1168bd,color:#fff,stroke:none
    classDef external fill:#999,color:#fff,stroke:none
    classDef storage fill:#438dd5,color:#fff,stroke:none

    class sre_engineer,platform_admin person
    class ai_sre system
    class vllm,openrouter,zabbix,telegram external
    class playground,qdrant storage
```

## Описание границ

| Граница | Внутри | Снаружи |
|---|---|---|
| **AI-SRE Platform** | LiteLLM Proxy, Registry, SRE-агент, Observability, Guardrails, PostgreSQL, Prometheus, Grafana, Langfuse | — |
| **Внешние сервисы** | — | vLLM (GPU-сервер), OpenRouter (облако), Telegram (облако) |
| **Полигон** | App, PostgreSQL, Redis, Zabbix Agent | Мониторится Zabbix, диагностируется SRE-агентом |
