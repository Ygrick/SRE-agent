# Спецификация: Serving & Config

## Назначение

Описание запуска, конфигурации, секретов и версий компонентов платформы.

## Docker Compose

Все компоненты разворачиваются через единый `docker-compose.yml`.

### Сервисы

```yaml
services:
  # === Платформа ===
  llm-gateway:
    build: ./gateway
    ports: ["8000:8000"]
    env_file: .env
    depends_on: [postgres, langfuse]

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
    depends_on: [llm-gateway, agent-registry, qdrant, playground-app]

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
  qdrant_data:
  grafana_data:
  langfuse_pg_data:
  zabbix_pg_data:
  playground_ssh_keys:   # SSH ключи для доступа SRE-агента к полигону
```

## Конфигурация (pydantic-settings)

### Gateway Settings

```python
class GatewaySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GATEWAY_", env_file=".env")

    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    database_url: str = Field(description="PostgreSQL connection string")
    encryption_key: str = Field(description="Fernet key for encrypting provider API keys")
    jwt_secret: str = Field(default="", description="JWT signing secret (if JWT auth enabled)")

    # Balancing
    circuit_breaker_failure_threshold: int = Field(default=3)
    circuit_breaker_recovery_timeout_seconds: int = Field(default=30)
    circuit_breaker_backoff_multiplier: float = Field(default=2.0)
    ema_alpha: float = Field(default=0.3)

    # Guardrails
    guardrails_prompt_injection_enabled: bool = Field(default=True)
    guardrails_secret_leak_enabled: bool = Field(default=True)
    guardrails_llm_classifier_enabled: bool = Field(default=False)
    guardrails_whitelist_agent_ids: list[str] = Field(default_factory=list)

    # Observability
    langfuse_public_key: str = Field(default="")
    langfuse_secret_key: str = Field(default="")
    langfuse_host: str = Field(default="http://langfuse:3000")
    prometheus_enabled: bool = Field(default=True)
```

### Agent Settings

```python
class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_", env_file=".env")

    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8002)
    gateway_url: str = Field(default="http://llm-gateway:8000")
    gateway_api_key: str = Field(description="API key for LLM Gateway")
    registry_url: str = Field(default="http://agent-registry:8001")
    qdrant_url: str = Field(default="http://qdrant:6333")
    qdrant_collection: str = Field(default="runbooks")
    telegram_bot_token: str = Field(description="Telegram Bot API token")
    telegram_chat_id: str = Field(description="Target chat for reports")
    codex_model: str = Field(default="qwen-2.5-coder-7b")
    max_shell_commands: int = Field(default=15)
    investigation_timeout_seconds: int = Field(default=300)
    playground_ssh_host: str = Field(default="playground-app")
    playground_ssh_port: int = Field(default=22)
    playground_ssh_user: str = Field(default="sre-agent")
    playground_ssh_key_path: str = Field(default="/run/secrets/ssh/id_ed25519")
```

## Файл `.env` (пример)

```env
# PostgreSQL
POSTGRES_USER=ai_sre
POSTGRES_PASSWORD=<generate-secure-password>

# Gateway
GATEWAY_DATABASE_URL=postgresql://ai_sre:<password>@postgres:5432/ai_sre
GATEWAY_ENCRYPTION_KEY=<fernet-key>
GATEWAY_JWT_SECRET=<jwt-secret>

# Agent
AGENT_GATEWAY_API_KEY=sk-sre-<generated>
AGENT_TELEGRAM_BOT_TOKEN=<bot-token>
AGENT_TELEGRAM_CHAT_ID=<chat-id>

# LLM Providers (задаются через Admin API, не через env)

# Langfuse
GATEWAY_LANGFUSE_PUBLIC_KEY=<pk>
GATEWAY_LANGFUSE_SECRET_KEY=<sk>

# OpenRouter (для регистрации через Admin API)
OPENROUTER_API_KEY=<key>
```

## Запуск

```bash
# 1. Склонировать репозиторий
git clone <repo-url> && cd sre-agent

# 2. Скопировать и заполнить .env
cp .env.example .env
# Отредактировать .env

# 3. Запустить всё
docker compose up -d

# 4. Проиндексировать Runbooks
docker compose exec sre-agent uv run python scripts/index_runbooks.py

# 5. Зарегистрировать LLM-провайдеров
curl -X POST http://localhost:8000/providers -H "Content-Type: application/json" -d '{
  "name": "vllm-local",
  "base_url": "http://vllm:8000/v1",
  "models": ["qwen-2.5-coder-7b"],
  "price_per_input_token": 0.0,
  "price_per_output_token": 0.0,
  "priority": 1
}'

# 6. Проверить health
curl http://localhost:8000/health
curl http://localhost:8001/health
curl http://localhost:8002/health

# 7. Открыть Grafana
# http://localhost:3000 (admin/admin)
```

## Миграции БД

**Инструмент:** Alembic (автогенерация миграций из SQLAlchemy моделей).

```bash
# Создать миграцию
uv run alembic revision --autogenerate -m "description"

# Применить миграции
uv run alembic upgrade head

# При старте в Docker — миграции применяются автоматически (entrypoint)
```

**Структура:**
```
alembic/
├── alembic.ini
├── env.py
└── versions/
    ├── 001_initial_providers.py
    ├── 002_agent_cards.py
    └── 003_api_keys.py
```

## Версии компонентов

| Компонент | Версия |
|---|---|
| Python | 3.12+ |
| FastAPI | 0.115+ |
| Pydantic | 2.x |
| pydantic-settings | 2.x |
| httpx | 0.28+ |
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
| PostgreSQL | 16 |
| Qdrant | latest (1.12+) |
| Prometheus | latest (2.x) |
| Grafana | latest (11.x) |
| Langfuse Server | latest (2.x, self-hosted) |
| Zabbix | 7.x |
| Redis | 7.x |
| Codex CLI | latest |
