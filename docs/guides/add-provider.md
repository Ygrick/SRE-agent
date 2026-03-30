# Как добавить нового LLM-провайдера

## Способ 1: Через config.yaml (статический)

Добавить блок в `gateway/litellm_config.yaml` → `model_list`:

### OpenAI-compatible провайдер (vLLM, Ollama, любой с /v1/chat/completions)

```yaml
- model_name: "my-model"              # Имя, по которому клиенты будут обращаться
  litellm_params:
    model: "openai/actual-model-name"  # Префикс openai/ + реальное имя модели
    api_base: "http://my-server:8000/v1"
    api_key: "os.environ/MY_PROVIDER_KEY"
    input_cost_per_token: 0.0          # Цена за input token (для cost tracking)
    output_cost_per_token: 0.0         # Цена за output token
  model_info:
    id: "my-provider-my-model"         # Уникальный ID deployment-а
```

Добавить в `.env`:
```env
MY_PROVIDER_KEY=sk-...
```

Перезапустить: `docker compose restart litellm`

### OpenRouter модель

```yaml
- model_name: "model-alias"
  litellm_params:
    model: "openai/vendor/model-name:variant"  # Формат OpenRouter
    api_base: "https://openrouter.ai/api/v1"
    api_key: "os.environ/OPENROUTER_API_KEY"
    input_cost_per_token: 0.0
    output_cost_per_token: 0.0
  model_info:
    id: "openrouter-model-alias"
```

### Балансировка между двумя провайдерами одной модели

Указать **одинаковый `model_name`** для двух deployments:

```yaml
# Deployment A
- model_name: "my-model"
  litellm_params:
    model: "openai/my-model"
    api_base: "http://provider-a:8000/v1"
    api_key: "os.environ/PROVIDER_A_KEY"
  model_info:
    id: "provider-a"

# Deployment B (тот же model_name!)
- model_name: "my-model"
  litellm_params:
    model: "openai/my-model"
    api_base: "http://provider-b:8000/v1"
    api_key: "os.environ/PROVIDER_B_KEY"
  model_info:
    id: "provider-b"
```

LiteLLM будет балансировать между ними по стратегии из `router_settings.routing_strategy`.

## Способ 2: Через API (динамический, без рестарта)

```bash
curl -X POST http://localhost:4000/model/new \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "model_name": "my-model",
    "litellm_params": {
      "model": "openai/actual-model-name",
      "api_base": "http://my-server:8000/v1",
      "api_key": "sk-..."
    },
    "model_info": {
      "id": "my-dynamic-model"
    }
  }'
```

Работает на лету, сохраняется в PostgreSQL (если `store_model_in_db: true`).

## Проверка

```bash
# Список моделей
curl http://localhost:4000/v1/models \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY}"

# Тестовый запрос
curl -X POST http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "my-model",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 50
  }'
```

## Поддерживаемые провайдеры

LiteLLM поддерживает 100+ провайдеров. Основные префиксы:

| Провайдер | Префикс `model` | `api_base` |
|---|---|---|
| OpenAI | `openai/gpt-4o` | (не нужен) |
| Anthropic | `anthropic/claude-3-5-sonnet` | (не нужен) |
| OpenAI-compatible (vLLM, Ollama, etc.) | `openai/model-name` | Обязательно |
| OpenRouter | `openai/vendor/model:tag` | `https://openrouter.ai/api/v1` |
| Azure OpenAI | `azure/deployment-name` | Azure endpoint |
| AWS Bedrock | `bedrock/model-id` | (не нужен, через boto3) |
