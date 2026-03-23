# AI-SRE: Автономный L1-агент первичной диагностики инцидентов

**Что за задача, для кого и какая боль сейчас**
Современные микросервисные инфраструктуры (Docker Compose, Kubernetes) генерируют большое количество рутинных алертов, связанных с утилизацией ресурсов (CPU, RAM, переполнение диска). Дежурные L1-инженеры тратят значительное время на однотипные операции: зайти по SSH на сервер, выполнить набор базовых read-only команд (`top`, `df -h`, `docker stats`, `cat /var/log/...`), сопоставить это с документацией (Runbooks) и передать контекст L2-инженеру.
Проект решает боль **"выгорания от рутины и долгого MTTA/MTTD"**, автоматизируя этап сбора контекста и формирования первичной гипотезы.

**Что именно сделает PoC на демо**

1. Имитируется инцидент: запускается bash-скрипт генератора нагрузки (стресс-тест CPU/RAM или забивание диска логами) в тестовой микросервисной среде (Java/PostgreSQL/Redis).
2. Система мониторинга Zabbix фиксирует аномалию и отправляет webhook.
3. Агент автоматически "просыпается", получает базовый контекст алерта.
4. Агент автономно подключается к терминалу ОС и выполняет серию read-only команд для расследования (исследование процессов, просмотр конфигов или последних строк логов).
5. Агент обращается в векторную базу Qdrant для поиска релевантного Runbook-а.
6. Всю логику рассуждений агента можно будет увидеть в Langfuse.
7. Итог: Агент отправляет в Telegram структурированное сообщение с указанием root-cause (причины) и рекомендациями по исправлению.

**Что НЕ делает PoC (явные out-of-scope)**

* **Запись и изменение состояния (Write-operations):** Агент работает строго в режиме *read-only*. Он не может перезапускать контейнеры, убивать процессы или менять конфигурацию.
* **Human-in-the-loop (HITL):** В рамках PoC агент работает полностью автономно от триггера до финального репорта, без запроса разрешений у человека.
* **Маскирование PII:** Защита персональных данных от утечки в логи (и в контекст LLM) осознанно вынесена за рамки PoC и будет реализована в MVP.
* **Сложные бизнес-ошибки:** Агент расследует только инфраструктурные инциденты (нагрузка CPU, RAM, Disk space), игнорируя логические ошибки внутри кода самого приложения.
* **Пользовательский интерфейс:** Специализированный UI (Streamlit и др.) не гарантируется; основным интерфейсом вывода результата является мессенджер Telegram.

## Архитектура

Платформа состоит из двух контуров:

**Инфраструктурная платформа:**
- **LLM API Gateway** — прокси для LLM-запросов с балансировкой (round-robin, weighted, latency-based), circuit breaker, streaming (SSE), guardrails, авторизацией и метриками (TTFT, TPOT, tokens, cost)
- **A2A Agent Registry** — реестр агентов по протоколу A2A v1.0 (a2a-sdk)
- **Observability** — OpenTelemetry → Prometheus → Grafana + Langfuse

**SRE-агент (потребитель платформы):**
- **Codex CLI** — ядро агента (shell execution, LLM reasoning)
- **Zabbix** → webhook → Codex → диагностика → Qdrant (Runbooks) → Telegram (отчёт)
- Все LLM-запросы идут через Gateway

## Стек

| Компонент | Технология |
|---|---|
| Backend | Python 3.12+, FastAPI, Pydantic v2 |
| Agent Core | OpenAI Codex CLI |
| LLM Providers | vLLM (локальный), OpenRouter |
| Agent Protocol | A2A v1.0 (a2a-sdk) |
| Knowledge Base | Qdrant |
| Monitoring (полигон) | Zabbix |
| Observability (платформа) | OpenTelemetry, Prometheus, Grafana, Langfuse |
| Database | PostgreSQL 16 |
| Deploy | Docker Compose |
| Package Manager | uv |

## Документация

- [System Design](docs/system-design.md) — архитектурные решения, модули, workflow, failure modes
- [Diagrams](docs/diagrams/) — C4 Context, Container, Component, Workflow, Data Flow
- Спецификации модулей:
  - [LLM Gateway](docs/specs/llm-gateway.md)
  - [Agent Registry](docs/specs/agent-registry.md)
  - [SRE Agent](docs/specs/sre-agent.md)
  - [Observability](docs/specs/observability.md)
  - [Guardrails](docs/specs/guardrails.md)
  - [Auth](docs/specs/auth.md)
  - [Retriever (Qdrant)](docs/specs/retriever.md)
  - [Serving & Config](docs/specs/serving-config.md)
  - [Load Testing](docs/specs/load-testing.md)
- [Product Proposal](docs/product-proposal.md)
- [Governance & Risks](docs/governance.md)
