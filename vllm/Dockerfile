# vLLM с поддержкой gpt-oss моделей (MXFP4 quantization)
# Требует NVIDIA GPU с ≥16GB VRAM (RTX 4090, A5000, H100)
#
# Build:  docker build -t vllm-gptoss -f vllm/Dockerfile vllm/
# Run:    docker run --gpus all -p 8000:8000 vllm-gptoss

FROM nvidia/cuda:12.8.0-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 python3.12-venv python3-pip curl git \
    && rm -rf /var/lib/apt/lists/*

RUN python3.12 -m venv /opt/vllm-env
ENV PATH="/opt/vllm-env/bin:$PATH"

# Install vLLM gpt-oss build (special pre-release with MXFP4 support)
RUN pip install --no-cache-dir --pre \
    "vllm==0.10.1+gptoss" \
    --extra-index-url https://wheels.vllm.ai/gpt-oss/ \
    --extra-index-url https://download.pytorch.org/whl/nightly/cu128 \
    --index-strategy unsafe-best-match

EXPOSE 8000

# gpt-oss-20b: ~16GB VRAM, MXFP4 already baked in, single GPU
ENTRYPOINT ["vllm", "serve"]
CMD ["openai/gpt-oss-20b", "--host", "0.0.0.0", "--port", "8000"]
