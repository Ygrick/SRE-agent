# Нагрузочное тестирование

## Запуск

```bash
# Убедитесь что платформа запущена
docker compose up -d

# Установите locust (если не установлен)
uv sync

# Сценарий 1: LLM Gateway — concurrent requests
uv run locust -f tests/load/locustfile.py LLMUser --host http://localhost:4000

# Сценарий 4: Multi-alert storm
uv run locust -f tests/load/locustfile.py AlertStormUser --host http://localhost:8002

# Headless mode (без UI)
uv run locust -f tests/load/locustfile.py LLMUser \
  --host http://localhost:4000 \
  --headless -u 10 -r 2 -t 60s \
  --csv tests/load/results/llm_gateway
```

Web UI: http://localhost:8089

## Сценарии

| # | Класс | Цель | Метрики |
|---|---|---|---|
| 1 | `LLMUser` | Throughput/latency Gateway | RPS, p50/p95 latency, TTFT, error rate |
| 3 | `LLMUser` (200+ users) | Stress test / saturation | Max RPS при p95 < 5s |
| 4 | `AlertStormUser` | Multi-alert storm | Concurrent investigations, dedup rate |

## Env vars

```bash
export LITELLM_MASTER_KEY=sk-master-changeme
export LOAD_TEST_MODEL=gpt-oss-120b
```
