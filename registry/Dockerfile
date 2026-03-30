FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml .
RUN uv sync --no-dev --no-install-project

# Create package structure: registry/app/
RUN mkdir -p registry
RUN touch registry/__init__.py
COPY app/ registry/app/

EXPOSE 8001

CMD ["uv", "run", "uvicorn", "registry.app.main:app", "--host", "0.0.0.0", "--port", "8001"]
