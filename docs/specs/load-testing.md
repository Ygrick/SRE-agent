# Спецификация: Нагрузочное тестирование

## Назначение

Проверка throughput, латентности и устойчивости LLM Gateway и SRE-агента под нагрузкой. Сравнение стратегий балансировки.

## Инструмент

**Locust** (Python) — описание сценариев на Python, единый стек с проектом, встроенный web UI с графиками, достаточная производительность для PoC (до 200+ concurrent users).

## Сценарии

### Сценарий 1: Concurrent LLM Requests

**Цель:** Измерение throughput и latency Gateway при массовых запросах.

```python
class LLMUser(HttpUser):
    wait_time = between(0.5, 2)

    @task
    def chat_completion(self):
        self.client.post("/v1/chat/completions", json={
            "model": "qwen-2.5-coder-7b",
            "messages": [{"role": "user", "content": "Explain CPU load average"}],
            "max_tokens": 100,
            "stream": False
        }, headers={"Authorization": f"Bearer {API_KEY}"})
```

**Параметры:**
- Users: 10, 50, 100, 200
- Ramp-up: 10 users/sec
- Duration: 5 min per step
- Провайдеры: 2 реплики vLLM + OpenRouter

**Метрики:**
- RPS (requests per second)
- Latency p50, p95, p99
- Error rate
- Throughput (tokens/sec)

### Сценарий 2: Provider Failover

**Цель:** Проверка circuit breaker и переключения на backup провайдер.

**Процедура:**
1. Запуск нагрузки (50 concurrent users)
2. Через 2 min: `docker compose stop vllm-replica-1` (один из провайдеров)
3. Наблюдение: как быстро Gateway переключается на оставшийся провайдер
4. Через 2 min: `docker compose start vllm-replica-1`
5. Наблюдение: как быстро провайдер возвращается в пул

**Метрики:**
- Время обнаружения отказа (от 5xx до circuit open)
- Количество потерянных запросов при переключении
- Время recovery (от start до возврата в пул)
- Latency до/во время/после отказа

### Сценарий 3: Peak Load (Stress Test)

**Цель:** Определение пределов Gateway и поведения при перегрузке.

**Параметры:**
- Users: от 10 до 500 (step-up: +50 каждые 2 min)
- Duration: до обнаружения degradation
- Без rate limiting (для определения natural limits)
- С rate limiting (для проверки backpressure)

**Метрики:**
- Точка насыщения (RPS, при которой latency начинает расти экспоненциально)
- Max RPS при p95 < 5s
- Поведение при перегрузке (graceful 429 vs crash)
- Memory/CPU usage Gateway

### Сценарий 4: Multi-Alert Storm

**Цель:** Проверка SRE-агента при массовых алертах.

**Процедура:**
1. Отправка 20 алертов за 1 минуту на `/webhooks/zabbix`
2. Наблюдение: сколько расследований запущено параллельно (max 5)
3. Проверка: дедупликация одинаковых алертов
4. Проверка: очередь для алертов сверх лимита

**Метрики:**
- Concurrent investigations
- Queue depth
- Investigation duration under load
- LLM Gateway load от агента

## Сравнение стратегий балансировки

Для каждой стратегии прогоняется Сценарий 1 (100 users, 5 min):

| Стратегия | Описание |
|---|---|
| `round_robin` | Циклический перебор |
| `weighted` | По статическим весам (70/30) |
| `latency_based` | Приоритет быстрому (EMA) |

**Сравнительные метрики:**
- p50/p95 latency
- Распределение трафика по провайдерам
- Error rate
- Utilization per provider

**Ожидаемый результат:** `latency_based` покажет лучший p95 при гетерогенных провайдерах (vLLM local vs OpenRouter cloud).

## Отчёт

По результатам тестирования формируется `docs/load-testing-report.md`:

1. Описание окружения (hardware, провайдеры, конфигурация)
2. Результаты каждого сценария (таблицы + графики из Grafana)
3. Сравнение стратегий балансировки (графики)
4. Выводы и рекомендации
5. Выявленные bottlenecks и план оптимизации

## Зависимости

- **Locust** — генерация нагрузки
- **Grafana** — визуализация метрик во время тестов (screenshots для отчёта)
- **Prometheus** — сбор метрик
