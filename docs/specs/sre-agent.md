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
base_url = "https://openrouter.ai/api/v1"
env_key = "OPENROUTER_API_KEY"
wire_api = "responses"

model = "stepfun/step-3.5-flash:free"

[approval]
mode = "full-auto"
```

**`AGENTS.md` (в рабочей директории):**
```markdown
# SRE Agent Instructions

Ты — L1 SRE-агент. Твоя задача — диагностировать инфраструктурный инцидент.

## Доступ к серверу
- Для выполнения команд на сервере используй: `ssh playground <command>`
- Пример: `ssh playground top -bn1`, `ssh playground df -h`
- Для Docker-команд: `ssh playground docker stats --no-stream`, `ssh playground docker logs --tail 50 <container>`

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
   codex exec --dangerously-bypass-approvals-and-sandbox --model stepfun/step-3.5-flash:free "{prompt}"
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

**Реализация:** см. [retriever.md](retriever.md) — embedding `intfloat/multilingual-e5-small`, cosine similarity, top-3, score > 0.7

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

## Доступ к полигону (SSH)

Codex выполняет диагностические команды на полигоне **через SSH**, а не через Docker socket.

**Почему SSH:**
- Изоляция: sre-agent не получает доступ к Docker daemon
- Реалистичность: в production SRE-агент подключается к серверам именно по SSH
- Безопасность: SSH-ключ ограничен конкретным хостом, нет рисков escape из контейнера

**Настройка:**
- В контейнере `playground-app` запущен SSH-сервер (OpenSSH)
- Пользователь `sre-agent` с ограниченными правами (read-only shell)
- SSH-ключ генерируется при деплое, приватный ключ монтируется в `sre-agent` контейнер
- Конфигурация в `~/.ssh/config` внутри sre-agent:
  ```
  Host playground
      HostName playground-app
      User sre-agent
      IdentityFile /run/secrets/playground_ssh_key
      StrictHostKeyChecking no
  ```

**Команды Codex через SSH:**
- Вместо `docker stats` → `ssh playground docker stats` (если Docker доступен на хосте)
- Или прямые команды: `ssh playground top -bn1`, `ssh playground df -h`
- AGENTS.md инструктирует Codex использовать `ssh playground <command>`

## Sandbox и безопасность

| Мера | Реализация |
|---|---|
| Read-only shell | AGENTS.md whitelist + SSH-пользователь без write-прав |
| Network isolation | SSH только к playground, LLM только через Gateway |
| Context budget | Codex built-in + truncation в AGENTS.md инструкциях |
| Max iterations | Codex timeout + max 15 команд в AGENTS.md |
| Dangerous commands | Whitelist бинарников, regex filter на операторы записи |
| SSH access control | Отдельный пользователь sre-agent, restricted shell |

## Ограничения

| Параметр | Значение |
|---|---|
| Max shell commands per investigation | 15 |
| Shell command timeout | 30s |
| Full investigation timeout | 5 min |
| Max stdout per command | 4000 chars (truncated) |
| Concurrent investigations | 5 |

## Трейсинг в Langfuse

Два уровня трейсинга:

**Уровень A — Gateway-level (автоматический):**
- Gateway записывает trace каждого LLM-запроса: model, provider, tokens, latency, cost
- Работает для всех агентов без дополнительной интеграции
- Span: `llm_request` с атрибутами provider, model, status, TTFT, TPOT

**Уровень B — Agent-level (парсинг `codex exec --json`):**
- `codex exec --json` выводит structured event stream в stdout
- Webhook handler читает этот поток и создаёт spans в Langfuse:
  - Parent trace: `investigation` (alert_id, host, severity)
  - Child spans: `llm_call`, `tool_call` (qdrant_search, telegram_send), `shell_command`
- Каждый shell_command span содержит: command, exit_code, stdout (truncated), duration
- Каждый tool_call span: tool name, input, output, duration

**Реализация:**
```python
# Webhook handler запускает Codex и парсит JSON events
process = await asyncio.create_subprocess_exec(
    "codex", "exec", "--json", "--quiet", prompt,
    stdout=asyncio.subprocess.PIPE
)
async for line in process.stdout:
    event = json.loads(line)
    match event["type"]:
        case "tool_call":
            langfuse.span(name=event["tool"], ...)
        case "completion":
            langfuse.span(name="llm_call", ...)
```

## Зависимости

- **Codex CLI** — ядро агента
- **LLM Gateway** — LLM-запросы
- **Qdrant** — Runbook search (MCP tool)
- **Telegram Bot API** — отчёты (MCP tool)
- **A2A Registry** — регистрация
- **Langfuse** — трейсинг (уровни A и B)
- **asyncssh / paramiko** — SSH-подключение к полигону
