# Сценарии использования SRE-агента

## Сценарий 1: Автоматическая диагностика инцидента (основной)

**Когда:** Zabbix детектирует аномалию на полигоне и отправляет webhook.

**Что происходит:**
1. Zabbix триггер срабатывает (CPU > 90%, Memory > 85%, Disk > 95%)
2. Zabbix Action отправляет POST на `http://sre-agent:8002/webhooks/zabbix`
3. Агент принимает алерт, проверяет дедупликацию
4. Запускается расследование:
   - Поиск релевантного Runbook в Qdrant (RAG)
   - SSH-подключение к playground, выполнение диагностических команд
   - LLM анализирует собранные данные + Runbook
5. Отчёт отправляется в Telegram
6. Trace записывается в Langfuse

**Как проверить:**
```bash
# 1. Поднять платформу
docker compose up -d

# 2. Запустить стресс-тест на playground (CPU)
docker compose exec playground-app bash /stress/cpu_stress.sh 60

# 3. Подождать 5 минут (Zabbix триггер)
# Или отправить алерт вручную:
curl -X POST http://localhost:8002/webhooks/zabbix \
  -H "Content-Type: application/json" \
  -d '{
    "alert_id": "test-cpu-001",
    "host": "playground",
    "trigger": "CPU usage > 90%",
    "severity": "high",
    "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'",
    "description": "CPU utilization exceeded 90% for 5 minutes"
  }'

# 4. Проверить статус расследования
curl http://localhost:8002/health | python3 -m json.tool

# 5. Проверить Telegram — отчёт должен прийти через 30-60 секунд
```

---

## Сценарий 2: Ручная отправка алерта (для тестирования)

**Когда:** Нужно проверить работу агента без Zabbix.

```bash
# CPU алерт
curl -X POST http://localhost:8002/webhooks/zabbix \
  -H "Content-Type: application/json" \
  -d '{
    "alert_id": "manual-cpu-'$(date +%s)'",
    "host": "playground",
    "trigger": "CPU usage > 90%",
    "severity": "high",
    "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'",
    "description": "CPU utilization exceeded 90% for 5 minutes"
  }'

# Memory алерт
curl -X POST http://localhost:8002/webhooks/zabbix \
  -H "Content-Type: application/json" \
  -d '{
    "alert_id": "manual-mem-'$(date +%s)'",
    "host": "playground",
    "trigger": "Memory usage > 85%",
    "severity": "high",
    "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'",
    "description": "Memory usage exceeded 85% for 5 minutes"
  }'

# Disk алерт
curl -X POST http://localhost:8002/webhooks/zabbix \
  -H "Content-Type: application/json" \
  -d '{
    "alert_id": "manual-disk-'$(date +%s)'",
    "host": "playground",
    "trigger": "Disk usage > 95%",
    "severity": "disaster",
    "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'",
    "description": "Disk usage exceeded 95%"
  }'
```

**Ожидаемый результат:**
- HTTP 202 Accepted с `investigation_id`
- Через 30-60 секунд: отчёт в Telegram
- `GET /health` показывает `investigations_completed` +1

---

## Сценарий 3: E2E демо (автоматический скрипт)

**Когда:** Полная демонстрация работы платформы.

```bash
bash scripts/e2e_demo.sh
```

Скрипт последовательно:
1. Проверяет все сервисы (LiteLLM, Registry, Playground, Grafana)
2. Проверяет A2A регистрацию агента
3. Отправляет CPU алерт
4. Ждёт завершения расследования (~30 секунд)
5. Показывает метрики и ссылки на дашборды

---

## Сценарий 4: Нагрузочное тестирование Gateway

**Когда:** Нужно проверить производительность LiteLLM Gateway.

```bash
# Web UI (интерактивно)
uv run locust -f tests/load/locustfile.py LLMUser --host http://localhost:4000
# Открыть http://localhost:8089

# Headless (в CI/CD)
uv run locust -f tests/load/locustfile.py LLMUser \
  --host http://localhost:4000 \
  --headless -u 10 -r 2 -t 60s
```

**Что измеряется:**
- RPS (requests per second)
- Latency p50/p95/p99
- TTFT (time to first token) для streaming
- Error rate

---

## Сценарий 5: Стресс-тест агента (Alert Storm)

**Когда:** Проверка поведения агента при массовых алертах.

```bash
uv run locust -f tests/load/locustfile.py AlertStormUser \
  --host http://localhost:8002 \
  --headless -u 5 -r 1 -t 30s
```

**Что проверяется:**
- Дедупликация (одинаковые alert_id → `skipped_duplicate`)
- Concurrency limit (max 5 активных расследований → HTTP 429)
- Время расследования под нагрузкой

---

## Где смотреть результаты

| Что | Где | URL |
|---|---|---|
| Отчёты агента | Telegram | Чат с ботом |
| LLM метрики | Grafana | http://localhost:3000 → LLM Gateway Overview |
| LLM трейсы | Langfuse | http://localhost:3001 → Traces |
| Метрики агента | API | `curl http://localhost:8002/health` |
| Prometheus raw | Prometheus | http://localhost:9090 |
| Логи агента | Docker | `docker compose logs sre-agent --follow` |
| Логи Gateway | Docker | `docker compose logs litellm --follow` |
| Мониторинг полигона | Zabbix | http://localhost:8080 (Admin/zabbix) |

---

## Типичные проблемы

| Проблема | Причина | Решение |
|---|---|---|
| 429 Too Many Requests | 5+ активных расследований | Подождать завершения текущих |
| `skipped_duplicate` | Повторный алерт с тем же alert_id | Использовать уникальный alert_id |
| Telegram "not configured" | Нет `AGENT_TELEGRAM_BOT_TOKEN` в .env | Создать бота через @BotFather |
| Investigation timeout | LLM не ответил за 5 минут | Проверить LiteLLM health, провайдеры |
| Empty report | Codex не поддерживает tool calls модели | Fallback с SSH работает автоматически |
| Qdrant search failed | Runbooks не проиндексированы | `uv run python agent/scripts/index_runbooks.py` |
