# Спецификация: SRE-агент

## Назначение

Автономный L1-агент диагностики инфраструктурных инцидентов. Принимает алерты от Zabbix, проводит read-only расследование через терминал, ищет релевантные Runbooks и формирует отчёт для L2-инженера.

## Ядро: Codex CLI

Используется OpenAI Codex CLI в режиме `exec` (non-interactive) или MCP server.

### Почему Codex

- Production-ready shell execution с sandbox, approval modes, обработкой ошибок
- Встроенное управление контекстным окном
- MCP client — подключение кастомных tools (Qdrant, Telegram)
- Поддержка любых OpenAI-compatible провайдеров (через наш Gateway)
- `AGENTS.md` — декларативная конфигурация поведения агента

### Конфигурация Codex

**`~/.codex/config.toml`:**
```toml
[provider]
name = "ai-sre-gateway"
baseURL = "http://llm-gateway:8000/v1"
envKey = "GATEWAY_API_KEY"

[model]
default = "qwen-2.5-coder-7b"

[approval]
mode = "never"  # full auto для автоматизации
```

**`AGENTS.md` (в рабочей директории):**
```markdown
# SRE Agent Instructions

Ты — L1 SRE-агент. Твоя задача — диагностировать инфраструктурный инцидент.

## Правила
- Выполняй ТОЛЬКО read-only команды
- Разрешённые команды: top, htop, ps, df, du, free, cat, tail, head, grep, docker stats, docker logs, journalctl, netstat, ss, lsof, uptime, vmstat, iostat
- ЗАПРЕЩЕНО: rm, kill, reboot, shutdown, mkfs, dd, mv, cp с перезаписью, любые операторы записи (>)
- Ограничивай вывод: используй tail -n 50, head -n 50, grep с фильтрами
- Максимум 15 команд за одно расследование

## Формат отчёта
1. Краткое описание инцидента
2. Выполненные команды и ключевые находки
3. Root cause (гипотеза)
4. Рекомендации по исправлению
5. Ссылка на Runbook (если найден)
```

## Webhook Handler

### Endpoint

```
POST /webhooks/zabbix
Content-Type: application/json

{
  "alert_id": "12345",
  "host": "playground-app",
  "trigger": "CPU usage > 90%",
  "severity": "high",
  "timestamp": "2026-03-23T10:15:00Z",
  "description": "CPU utilization has exceeded 90% for the last 5 minutes"
}
```

### Обработка

1. Валидация payload (Pydantic model)
2. Дедупликация по `alert_id` (in-memory set с TTL 10 min)
3. Формирование промпта:
   ```
   Получен алерт от Zabbix:
   - Host: {host}
   - Trigger: {trigger}
   - Severity: {severity}
   - Время: {timestamp}
   - Описание: {description}

   Проведи диагностику. Используй доступные команды терминала.
   При необходимости найди релевантный Runbook через инструмент qdrant_search.
   По завершении отправь отчёт через telegram_send.
   ```
4. Запуск Codex:
   ```bash
   codex exec --quiet --model qwen-2.5-coder-7b --approval-mode never "{prompt}"
   ```
   Или через MCP server (для более сложных сценариев с сессиями).
5. Логирование trace в Langfuse

### Ответ

```json
{
  "status": "accepted",
  "alert_id": "12345",
  "investigation_id": "uuid"
}
```

HTTP 202 Accepted (асинхронная обработка).

## MCP Tools (кастомные)

### qdrant_search

```json
{
  "name": "qdrant_search",
  "description": "Поиск релевантных Runbooks по описанию инцидента",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {"type": "string", "description": "Описание инцидента или ключевые слова"}
    },
    "required": ["query"]
  }
}
```

**Реализация:**
- Embedding запроса через Gateway (model: text-embedding-3-small или локальная)
- Cosine similarity search в Qdrant
- Top-3 results, score > 0.7
- Возврат: concatenated text chunks

### telegram_send

```json
{
  "name": "telegram_send",
  "description": "Отправка отчёта об инциденте в Telegram",
  "inputSchema": {
    "type": "object",
    "properties": {
      "message": {"type": "string", "description": "Текст отчёта в формате Markdown"}
    },
    "required": ["message"]
  }
}
```

**Реализация:**
- Telegram Bot API: `sendMessage` с `parse_mode=Markdown`
- Chat ID из конфигурации (env var)
- Retry: 3 attempts с exponential backoff

## Регистрация в A2A Registry

При старте сервиса:
1. Формирование Agent Card (см. spec agent-registry)
2. `POST /agents` к Registry
3. При повторном старте — `PUT /agents/{id}` (update)
4. Health endpoint: `GET /health` — для периодического probe от Registry

## Sandbox и безопасность

| Мера | Реализация |
|---|---|
| Read-only shell | Codex sandbox + AGENTS.md whitelist + Python wrapper |
| Network isolation | Codex sandbox: network disabled (кроме Gateway) |
| Context budget | Codex built-in + truncation в AGENTS.md инструкциях |
| Max iterations | Codex timeout + max 15 команд в AGENTS.md |
| Dangerous commands | Whitelist бинарников, regex filter на операторы записи |

## Ограничения

| Параметр | Значение |
|---|---|
| Max shell commands per investigation | 15 |
| Shell command timeout | 30s |
| Full investigation timeout | 5 min |
| Max stdout per command | 4000 chars (truncated) |
| Concurrent investigations | 5 |

## Зависимости

- **Codex CLI** — ядро агента
- **LLM Gateway** — LLM-запросы
- **Qdrant** — Runbook search (MCP tool)
- **Telegram Bot API** — отчёты (MCP tool)
- **A2A Registry** — регистрация
- **Langfuse** — трейсинг
