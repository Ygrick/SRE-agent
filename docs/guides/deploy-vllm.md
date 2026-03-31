# Развёртывание vLLM с gpt-oss-20b на GPU

## О модели

**openai/gpt-oss-20b** — открытая модель от OpenAI (Apache 2.0).

| Параметр | Значение |
|---|---|
| Всего параметров | 21B |
| Активных (MoE) | 3.6B |
| Квантизация | MXFP4 (встроена, не нужна отдельная) |
| VRAM | ~16GB |
| Контекст | до 1M tokens |

## Требования

| Компонент | Минимум | Рекомендуется |
|---|---|---|
| GPU | 1x NVIDIA ≥16GB VRAM | 1x RTX 4090 / A100 / H100 |
| RAM | 32GB | 64GB |
| Диск | 50GB (для весов модели) | SSD |
| CUDA | 12.x | 12.8 |
| Docker | 24.0+ с nvidia-container-toolkit | — |

**Совместимые GPU:** RTX 4090 (24GB), RTX 3090 (24GB), A5000 (24GB), A100 (40/80GB), H100 (80GB), L40S (48GB).

> Для gpt-oss-120b потребуется ≥60GB VRAM (H100 80GB или multi-GPU с tensor parallelism).

## Установка nvidia-container-toolkit

```bash
# Ubuntu/Debian
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Проверка
docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu22.04 nvidia-smi
```

## Запуск

### Вариант 1: Docker Compose (рекомендуется)

```bash
# Из корня проекта
docker compose -f vllm/docker-compose.vllm.yml up -d

# Первый запуск: скачивание модели (~40GB), 10-30 минут
docker compose -f vllm/docker-compose.vllm.yml logs -f vllm
```

### Вариант 2: Docker run

```bash
docker build -t vllm-gptoss -f vllm/Dockerfile vllm/

docker run -d --gpus all \
  -p 8000:8000 \
  -v vllm_cache:/root/.cache/huggingface \
  --name vllm \
  vllm-gptoss
```

### Вариант 3: Без Docker (pip)

```bash
# Требуется специальная сборка vLLM с поддержкой gpt-oss (MXFP4)
uv pip install --pre "vllm==0.10.1+gptoss" \
    --extra-index-url https://wheels.vllm.ai/gpt-oss/ \
    --extra-index-url https://download.pytorch.org/whl/nightly/cu128 \
    --index-strategy unsafe-best-match

vllm serve openai/gpt-oss-20b
```

> Стандартная версия vLLM из PyPI **не поддерживает** gpt-oss модели — нужна сборка `+gptoss`.

## Проверка

```bash
# Health
curl http://localhost:8000/health

# Список моделей
curl http://localhost:8000/v1/models | python3 -m json.tool

# Chat Completions API
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/gpt-oss-20b",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 50
  }'

# Responses API (для Codex CLI)
curl -X POST http://localhost:8000/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/gpt-oss-20b",
    "input": "Hello!"
  }'
```

## Подключение к AI-SRE Platform

### 1. Добавить в LiteLLM config

В `gateway/litellm_config.yaml`:

```yaml
model_list:
  # ... существующие модели ...

  - model_name: "gpt-oss-20b"
    litellm_params:
      model: "openai/openai/gpt-oss-20b"
      api_base: "http://<VLLM_HOST>:8000/v1"  # IP GPU-сервера
      api_key: "none"
      input_cost_per_token: 0.0
      output_cost_per_token: 0.0
    model_info:
      id: "vllm-gpt-oss-20b"
```

Если vLLM на том же хосте: `api_base: "http://host.docker.internal:8000/v1"`

```bash
docker compose restart litellm
```

### 2. Подключить Codex CLI напрямую (без SSE Fix Proxy)

vLLM поддерживает `/v1/responses` — Codex может работать напрямую.

В `agent/codex_workdir/.codex/config.toml`:

```toml
model = "openai/gpt-oss-20b"
model_provider = "vllm"

[model_providers.vllm]
name = "vLLM Local"
base_url = "http://<VLLM_HOST>:8000/v1"
env_key = "VLLM_API_KEY"
wire_api = "responses"
supports_websockets = false
```

> С vLLM SSE Fix Proxy **не нужен** — vLLM отправляет все SSE events корректно.

### 3. Обновить модель агента

В `.env`:
```env
AGENT_CODEX_MODEL=openai/gpt-oss-20b
```

```bash
docker compose up -d --build sre-agent
```

## gpt-oss-120b (multi-GPU)

Для gpt-oss-120b с tensor parallelism на 2+ GPU:

```yaml
# vllm/docker-compose.vllm.yml
services:
  vllm:
    command: >
      openai/gpt-oss-120b
      --host 0.0.0.0
      --port 8000
      --tensor-parallel-size 2
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 2
              capabilities: [gpu]
```

## Troubleshooting

| Проблема | Решение |
|---|---|
| `CUDA out of memory` | Проверить `nvidia-smi`, убедиться что GPU свободен. Для 20B нужно ≥16GB. |
| `ModuleNotFoundError: vllm` | Установить специальную сборку `vllm==0.10.1+gptoss` (не стандартную) |
| Долгая загрузка модели | Нормально при первом запуске (~40GB). Используйте `HF_TOKEN` для ускорения. |
| `nvidia-smi` не работает в Docker | Установить nvidia-container-toolkit, перезапустить Docker daemon |
| vLLM crash при старте | Проверить совместимость CUDA driver ≥ 12.x |
