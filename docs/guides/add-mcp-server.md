# Добавление MCP-сервера к SRE Agent

SRE Agent использует [Codex CLI](https://github.com/openai/codex) для проведения расследований. Codex поддерживает [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) — стандарт подключения внешних инструментов к LLM-агентам.

MCP-серверы расширяют возможности агента: поиск в базе знаний, интеграция с внешними API, доступ к БД и т.д.

## Встроенные MCP-серверы

| Сервер | Tool | Описание |
|--------|------|----------|
| `qdrant-search` | `qdrant_search` | Поиск Runbooks в Qdrant по описанию инцидента |

## Как подключить существующий MCP-сервер

### Шаг 1: Добавьте секцию в `agent/codex_workdir/.codex/config.toml`

```toml
[mcp_servers.my-server]
command = "npx"
args = ["-y", "@my-org/my-mcp-server"]
env = { API_KEY = "secret" }
startup_timeout_sec = 15
tool_timeout_sec = 60
```

### Шаг 2: Перезапустите агент

```bash
docker compose up -d --build sre-agent
```

### Шаг 3: Упомяните tool в AGENTS.md (опционально)

Если хотите чтобы агент знал о новом инструменте, добавьте упоминание в `agent/codex_workdir/AGENTS.md`:

```markdown
## Доступные инструменты
- `my_tool` — описание, когда использовать
```

## Как создать свой MCP-сервер

### Минимальный MCP-сервер на Python (stdio)

Создайте файл `agent/mcp_servers/my_server.py`:

```python
import json
import sys

def _respond(request_id, result):
    msg = json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result})
    sys.stdout.write(f"Content-Length: {len(msg.encode())}\r\n\r\n{msg}")
    sys.stdout.flush()

def _handle(request):
    method = request.get("method", "")
    rid = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        _respond(rid, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "my-server", "version": "1.0.0"},
        })

    elif method == "tools/list":
        _respond(rid, {"tools": [{
            "name": "my_tool",
            "description": "What this tool does",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Input parameter"}
                },
                "required": ["query"],
            },
        }]})

    elif method == "tools/call":
        query = params.get("arguments", {}).get("query", "")
        result = f"Result for: {query}"  # Ваша логика здесь
        _respond(rid, {"content": [{"type": "text", "text": result}]})

    elif method == "ping":
        _respond(rid, {})

def main():
    while True:
        content_length = 0
        while True:
            line = sys.stdin.readline()
            if not line:
                return
            line = line.strip()
            if not line:
                break
            if line.lower().startswith("content-length:"):
                content_length = int(line.split(":", 1)[1].strip())
        if content_length == 0:
            continue
        body = sys.stdin.read(content_length)
        _handle(json.loads(body))

if __name__ == "__main__":
    main()
```

### Подключение в config.toml

```toml
[mcp_servers.my-server]
command = "python3"
args = ["-m", "agent.mcp_servers.my_server"]
env = { PYTHONPATH = "/app" }
startup_timeout_sec = 15
tool_timeout_sec = 30
```

### Не забудьте добавить в Dockerfile

В `agent/Dockerfile` уже есть строка:
```dockerfile
COPY mcp_servers/ agent/mcp_servers/
```

Ваш сервер будет автоматически скопирован при сборке.

## Параметры конфигурации

| Параметр | Тип | Default | Описание |
|----------|-----|---------|----------|
| `command` | string | required | Команда запуска (python3, npx, node) |
| `args` | array | — | Аргументы командной строки |
| `env` | object | — | Переменные окружения (ключ-значение) |
| `cwd` | string | — | Рабочая директория |
| `startup_timeout_sec` | number | 10 | Таймаут на запуск сервера |
| `tool_timeout_sec` | number | 60 | Таймаут на выполнение tool |
| `enabled` | boolean | true | Включить/выключить без удаления |
| `enabled_tools` | array | — | Whitelist конкретных tools |
| `disabled_tools` | array | — | Blacklist конкретных tools |

## Примеры подключения популярных MCP-серверов

### Файловая система
```toml
[mcp_servers.filesystem]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/data"]
```

### GitHub
```toml
[mcp_servers.github]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
env = { GITHUB_TOKEN = "ghp_..." }
```

### PostgreSQL
```toml
[mcp_servers.postgres]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-postgres", "postgresql://user:pass@host/db"]
```

## Отладка

```bash
# Проверить что MCP сервер работает (внутри контейнера)
docker compose exec sre-agent python3 -m agent.mcp_servers.qdrant_search_server

# Затем отправить JSON-RPC запрос вручную:
# Content-Length: 58
#
# {"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}
```
