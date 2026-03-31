# Развёртывание vLLM с gpt-oss-20b на GPU

## Требования

| Компонент | Минимум | Рекомендуется |
|---|---|---|
| GPU | 1x NVIDIA с ≥24GB VRAM | 1x A100 80GB или 2x RTX 4090 |
| RAM | 32GB | 64GB |
| Диск | 50GB свободных (для весов модели) | SSD |
| ОС | Linux (Ubuntu 22.04+) | Ubuntu 22.04 |
| Docker | 24.0+ с nvidia-container-toolkit | — |

**Совместимые GPU:**
- RTX 3090 (24GB) — минимум, с ограничением контекста
- RTX 4090 (24GB) — хорошо
- A100 (40GB / 80GB) — оптимально
- L40S (48GB) — оптимально
- 2x RTX 3090/4090 — с tensor-parallel=2

## Быстрый старт

### 1. Установить nvidia-container-toolkit

```bash
# Ubuntu/Debian
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### 2. Запустить vLLM

```bash
# Из корня проекта
docker compose -f vllm/docker-compose.vllm.yml up -d

# Первый запуск: скачивание модели (~40GB) может занять 10-30 минут
# Проверить прогресс:
docker compose -f vllm/docker-compose.vllm.yml logs -f vllm
```

### 3. Проверить работу

```bash
# Health
curl http://localhost:8000/health

# Модели
curl http://localhost:8000/v1/models

# Chat completion
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/gpt-oss-20b",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 50
  }'
```

### 4. Подключить к AI-SRE Platform

Добавьте в `gateway/litellm_config.yaml` новый deployment:

```yaml
model_list:
  # ... существующие модели ...

  # vLLM (локальный GPU)
  - model_name: "gpt-oss-20b"
    litellm_params:
      model: "openai/openai/gpt-oss-20b"
      api_base: "http://<VLLM_HOST>:8000/v1"  # IP вашего GPU-сервера
      api_key: "none"
      input_cost_per_token: 0.0
      output_cost_per_token: 0.0
    model_info:
      id: "vllm-gpt-oss-20b"
```

Перезапустите LiteLLM:
```bash
docker compose restart litellm
```

Или добавьте через API (без рестарта):
```bash
curl -X POST http://localhost:4000/model/new \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "model_name": "gpt-oss-20b",
    "litellm_params": {
      "model": "openai/openai/gpt-oss-20b",
      "api_base": "http://<VLLM_HOST>:8000/v1",
      "api_key": "none"
    }
  }'
```

### 5. Обновить модель агента

В `.env`:
```env
AGENT_CODEX_MODEL=gpt-oss-20b
```

Перезапустите агента:
```bash
docker compose restart sre-agent
```

## Варианты конфигурации vLLM

### Один GPU (24GB VRAM)

```yaml
command: >
  --model openai/gpt-oss-20b
  --dtype auto
  --max-model-len 16384
  --gpu-memory-utilization 0.90
```

### Два GPU (tensor parallel)

```yaml
command: >
  --model openai/gpt-oss-20b
  --dtype auto
  --max-model-len 32768
  --tensor-parallel-size 2
  --gpu-memory-utilization 0.90
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 2
          capabilities: [gpu]
```

### Квантизованная модель (меньше VRAM)

Если модель поддерживает AWQ/GPTQ квантизацию:
```yaml
command: >
  --model openai/gpt-oss-20b
  --quantization awq
  --dtype half
  --max-model-len 32768
  --gpu-memory-utilization 0.90
```

## API endpoints vLLM

| Endpoint | Поддержка | Примечание |
|---|---|---|
| `/v1/chat/completions` | Да | Основной, через LiteLLM |
| `/v1/completions` | Да | Legacy |
| `/v1/models` | Да | Список моделей |
| `/v1/responses` | Зависит от версии | Нужна vLLM ≥ 0.8.x с `--enable-responses-api` |
| `/health` | Да | Health check |

**Для Codex CLI:** Если vLLM поддерживает `/v1/responses`, Codex может подключаться напрямую. Иначе — через LiteLLM (Chat Completions API) + наш SSE Fix Proxy.

## Troubleshooting

| Проблема | Решение |
|---|---|
| `CUDA out of memory` | Уменьшить `--max-model-len` или `--gpu-memory-utilization` |
| Медленная загрузка модели | Проверить скорость интернета, использовать `HF_TOKEN` для HuggingFace |
| `nvidia-smi` не работает | Установить nvidia-container-toolkit |
| vLLM crash при старте | Проверить совместимость CUDA driver с vLLM image |
