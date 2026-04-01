# Спецификация: Serving & Config

## Назначение

Описание запуска, конфигурации, секретов и версий компонентов платформы.

## Docker Compose

Все компоненты разворачиваются через единый `docker-compose.yml`.

### Сервисы

```yaml
services:
  # === LLM Gateway (LiteLLM) ===
  litellm:
    image: docker.litellm.ai/berriai/litellm:main-stable
    ports: ["4000:4000"]
    env_file: .env
    volumes:
      - ./gateway/litellm_config.yaml:/app/config.yaml
      - ./gateway/custom_guardrail.py:/app/custom_guardrail.py
    command: ["--config", "/app/config.yaml", "--port", "4000"]
    depends_on: [litellm-postgres, langfuse]

  litellm-postgres:
    image: postgres:16-alpine
    volumes: ["litellm_pg_data:/var/lib/postgresql/data"]
    environment:
      POSTGRES_DB: litellm
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}

  # === Наши сервисы ===
  agent-registry:
    build: ./registry
    ports: ["8001:8001"]
    env_file: .env
    depends_on: [postgres]

  sre-agent:
    build: ./agent
    ports: ["8002:8002"]
    env_file: .env
    volumes:
      - playground_ssh_keys:/run/secrets/ssh:ro
    depends_on: [litellm, agent-registry, qdrant, playground-app]

  # === Хранение ===
  postgres:
    image: postgres:16-alpine
    ports: ["5432:5432"]
    volumes: ["postgres_data:/var/lib/postgresql/data"]
    environment:
      POSTGRES_DB: ai_sre
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}

  qdrant:
    image: qdrant/qdrant:latest
    ports: ["6333:6333"]
    volumes: ["qdrant_data:/qdrant/storage"]

  # === Observability ===
  prometheus:
    image: prom/prometheus:latest
    ports: ["9090:9090"]
    volumes: ["./config/prometheus.yml:/etc/prometheus/prometheus.yml"]

  grafana:
    image: grafana/grafana:latest
    ports: ["3000:3000"]
    volumes:
      - "grafana_data:/var/lib/grafana"
      - "./config/grafana/dashboards:/etc/grafana/provisioning/dashboards"
      - "./config/grafana/datasources:/etc/grafana/provisioning/datasources"

  langfuse:
    image: langfuse/langfuse:latest
    ports: ["3001:3000"]
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@langfuse-postgres:5432/langfuse
    depends_on: [langfuse-postgres]

  langfuse-postgres:
    image: postgres:16-alpine
    volumes: ["langfuse_pg_data:/var/lib/postgresql/data"]
    environment:
      POSTGRES_DB: langfuse
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}

  # === Мониторинг полигона ===
  zabbix-server:
    image: zabbix/zabbix-server-pgsql:latest
    ports: ["10051:10051"]
    environment:
      DB_SERVER_HOST: zabbix-postgres
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    depends_on: [zabbix-postgres]

  zabbix-web:
    image: zabbix/zabbix-web-nginx-pgsql:latest
    ports: ["8080:8080"]
    depends_on: [zabbix-server]

  zabbix-postgres:
    image: postgres:16-alpine
    volumes: ["zabbix_pg_data:/var/lib/postgresql/data"]

  # === Полигон ===
  playground-app:
    build: ./playground
    ports:
      - "8090:8090"
      - "2222:22"       # SSH для SRE-агента
    volumes:
      - playground_ssh_keys:/home/sre-agent/.ssh:ro
    depends_on: [playground-postgres, playground-redis]

  playground-postgres:
    image: postgres:16-alpine
    ports: ["5433:5432"]
    environment:
      POSTGRES_DB: playground
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}

  playground-redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  zabbix-agent:
    image: zabbix/zabbix-agent2:latest
    environment:
      ZBX_HOSTNAME: playground
      ZBX_SERVER_HOST: zabbix-server
    depends_on: [zabbix-server, playground-app]
    pid: "host"

volumes:
  postgres_data:
  litellm_pg_data:
  qdrant_data:
  grafana_data:
  langfuse_pg_data:
  zabbix_pg_data:
  playground_ssh_keys:
```

## Конфигурация

### LiteLLM Gateway

Конфигурация через `gateway/litellm_config.yaml` — см. [llm-gateway.md](llm-gateway.md).

Переменные среды для LiteLLM:
```env
LITELLM_MASTER_KEY=sk-master-<generated>
LITELLM_DATABASE_URL=postgresql://ai_sre:<password>@litellm-postgres:5432/litellm
VLLM_API_KEY=<vllm-token-if-any>
OPENROUTER_API_KEY=<openrouter-key>
LANGFUSE_PUBLIC_KEY=<pk>
LANGFUSE_SECRET_KEY=<sk>
LANGFUSE_HOST=http://langfuse:3000
```

### Agent Settings (pydantic-settings)

```python
class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_", env_file=".env")

    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8002)
    gateway_url: str = Field(default="http://litellm:4000")
    gateway_api_key: str = Field(description="LiteLLM virtual key")
    registry_url: str = Field(default="http://agent-registry:8001")
    qdrant_url: str = Field(default="http://qdrant:6333")
    qdrant_collection: str = Field(default="runbooks")
    telegram_bot_token: str = Field(description="Telegram Bot API token")
    telegram_chat_id: str = Field(description="Target chat for reports")
    codex_model: str = Field(default="stepfun/step-3.5-flash:free")
    max_shell_commands: int = Field(default=15)
    investigation_timeout_seconds: int = Field(default=300)
    ssh_user: str = Field(default="sre-agent")
    ssh_key_path: str = Field(default="/run/secrets/ssh/id_ed25519")
```

### Registry Settings (pydantic-settings)

```python
class RegistrySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REGISTRY_", env_file=".env")

    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8001)
    database_url: str = Field(description="PostgreSQL connection string")
    api_key: str = Field(description="API key for registry access")
```

## Файл `.env` (пример)

```env
# PostgreSQL (общий пользователь)
POSTGRES_USER=ai_sre
POSTGRES_PASSWORD=<generate-secure-password>

# LiteLLM Gateway
LITELLM_MASTER_KEY=sk-master-<generated>
LITELLM_DATABASE_URL=postgresql://ai_sre:<password>@litellm-postgres:5432/litellm

# LLM Providers
VLLM_API_KEY=<token>
OPENROUTER_API_KEY=<key>

# Langfuse
LANGFUSE_PUBLIC_KEY=<pk>
LANGFUSE_SECRET_KEY=<sk>
LANGFUSE_HOST=http://langfuse:3000

# Agent
AGENT_GATEWAY_URL=http://litellm:4000
AGENT_GATEWAY_API_KEY=sk-sre-<virtual-key>
AGENT_TELEGRAM_BOT_TOKEN=<bot-token>
AGENT_TELEGRAM_CHAT_ID=<chat-id>

# Registry
REGISTRY_DATABASE_URL=postgresql://ai_sre:<password>@postgres:5432/ai_sre
REGISTRY_API_KEY=<generated>
```

## Запуск

```bash
# 1. Склонировать репозиторий
git clone <repo-url> && cd sre-agent

# 2. Скопировать и заполнить .env
cp .env.example .env

# 3. Запустить всё
docker compose up -d

# 4. Создать virtual key для SRE-агента
curl -X POST http://localhost:4000/key/generate \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
  -d '{"key_alias": "sre-agent-01", "max_budget": 10.0}'

# 5. Проиндексировать Runbooks
docker compose exec sre-agent uv run python scripts/index_runbooks.py

# 6. Проверить health
curl http://localhost:4000/health     # LiteLLM
curl http://localhost:8001/health     # Registry
curl http://localhost:8002/health     # SRE Agent

# 7. Открыть Grafana
# http://localhost:3000 (admin/admin)
```

## Миграции БД

**LiteLLM:** Использует Prisma, миграции применяются автоматически при старте.

**Agent Registry:** Alembic (автогенерация миграций из SQLAlchemy моделей).

```bash
# Создать миграцию
uv run alembic revision --autogenerate -m "description"

# Применить миграции
uv run alembic upgrade head

# При старте в Docker — миграции применяются автоматически (entrypoint)
```

**Структура:**
```
registry/
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 001_initial_agent_cards.py
```

## Версии компонентов

| Компонент | Версия |
|---|---|
| **Наш код** | |
| Python | 3.12+ |
| FastAPI | 0.115+ |
| Pydantic | 2.x |
| pydantic-settings | 2.x |
| SQLAlchemy | 2.x (async) |
| Alembic | 1.x |
| asyncpg | 0.30+ |
| a2a-sdk | 0.3+ |
| structlog | 24.x |
| opentelemetry-sdk | 1.x |
| opentelemetry-exporter-prometheus | 0.x |
| langfuse | 2.x (Python SDK) |
| sentence-transformers | 3.x |
| locust | 2.x |
| **Docker images** | |
| LiteLLM Proxy | main-stable |
| PostgreSQL | 16-alpine |
| Qdrant | latest (1.12+) |
| Prometheus | latest (2.x) |
| Grafana | latest (11.x) |
| Langfuse Server | latest (2.x) |
| Zabbix | 7.x |
| Redis | 7.x |
| Codex CLI | latest |
