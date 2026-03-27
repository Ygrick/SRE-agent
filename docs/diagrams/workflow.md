# Workflow Diagram — Обработка инцидента

Пошаговое выполнение запроса. Разбито на три фазы для читаемости.

## Фаза 1: Приём алерта

```mermaid
flowchart TD
    A["Генератор нагрузки<br/>(stress CPU / fill disk)"] --> B["Полигон: аномалия"]
    B --> C["Zabbix: триггер сработал"]
    C --> D["POST /webhooks/zabbix"]

    D --> E{"Payload валиден?"}
    E -- "Нет" --> E1["400 Bad Request"]
    E -- "Да" --> F{"Алерт уже<br/>обработан?"}
    F -- "Да" --> F1["200 OK (skip)"]
    F -- "Нет" --> G["Формирование промпта → Codex exec"]

    style E1 fill:#c0392b,color:#fff
    style F1 fill:#7f8c8d,color:#fff
    style G fill:#27ae60,color:#fff
```

## Фаза 2: Цикл диагностики (внутри Codex)

```mermaid
flowchart TD
    G["Codex exec запущен"] --> LLM["Codex → LiteLLM:<br/>POST /v1/chat/completions"]

    LLM --> AUTH{"Auth OK?"}
    AUTH -- "Fail" --> AUTH_ERR["401 → Сессия завершена"]
    AUTH -- "OK" --> GR{"Guardrails OK?"}
    GR -- "Blocked" --> GR_ERR["422 → Codex получает<br/>ошибку, пробует<br/>переформулировать"]
    GR_ERR --> LLM
    GR -- "OK" --> ROUTE{"Есть здоровый<br/>провайдер?"}

    ROUTE -- "Нет" --> ROUTE_ERR["503 → Сессия завершена"]
    ROUTE -- "Да" --> PROXY["Streaming Proxy → Provider"]

    PROXY --> PROXY_OK{"Ответ получен?"}
    PROXY_OK -- "Timeout/5xx" --> CB["Cooldown: deployment excluded<br/>Retry другой провайдер"]
    CB --> ROUTE
    PROXY_OK -- "OK (SSE)" --> METRICS["Метрики: TTFT, TPOT,<br/>tokens, cost"]

    METRICS --> CODEX["Codex обрабатывает ответ LLM"]

    CODEX --> DECISION{"Решение Codex"}

    DECISION -- "Shell команда" --> SHELL["Выполнение в sandbox"]
    SHELL --> WL{"В whitelist?"}
    WL -- "Нет" --> BLOCKED["Блокировка → stderr"]
    WL -- "Да" --> EXEC["stdout/stderr<br/>(truncated 4000 chars)"]
    BLOCKED --> CODEX
    EXEC --> CODEX

    DECISION -- "Поиск Runbook" --> QDRANT["MCP: qdrant_search"]
    QDRANT --> QD_OK{"Qdrant доступен?"}
    QD_OK -- "Нет" --> QD_SKIP["Работа без Runbook"]
    QD_OK -- "Да" --> QD_RES["Top-K результаты"]
    QD_SKIP --> CODEX
    QD_RES --> CODEX

    DECISION -- "Готов отчёт" --> REPORT["Переход к отправке"]

    style AUTH_ERR fill:#c0392b,color:#fff
    style ROUTE_ERR fill:#c0392b,color:#fff
    style GR_ERR fill:#e67e22,color:#fff
    style BLOCKED fill:#e67e22,color:#fff
    style QD_SKIP fill:#e67e22,color:#fff
    style REPORT fill:#27ae60,color:#fff
```

## Фаза 3: Отправка отчёта

```mermaid
flowchart TD
    REPORT["Codex сформировал отчёт"] --> TG["MCP: telegram_send"]

    TG --> TG_OK{"Telegram доступен?"}
    TG_OK -- "Нет" --> RETRY{"Retry < 3?"}
    RETRY -- "Да" --> TG
    RETRY -- "Нет" --> TG_FALLBACK["Отчёт сохранён<br/>только в Langfuse"]
    TG_OK -- "Да" --> TG_SENT["Отчёт доставлен<br/>в Telegram"]

    TG_SENT --> DONE["Сессия завершена<br/>Trace записан в Langfuse"]
    TG_FALLBACK --> DONE

    style TG_FALLBACK fill:#e67e22,color:#fff
    style DONE fill:#27ae60,color:#fff
```

Таймауты и SLA: [system-design.md](../system-design.md#9-ограничения)
