FROM python:3.12-slim

WORKDIR /app

# System deps: curl, SSH client, git, Node.js (for Codex CLI)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    openssh-client \
    git \
    ca-certificates \
    gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Codex CLI globally
RUN npm install -g @openai/codex

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files and install
COPY pyproject.toml .
RUN uv sync --no-dev --no-install-project

# Create package structure
RUN mkdir -p agent
RUN touch agent/__init__.py
COPY app/ agent/app/
COPY mcp_servers/ agent/mcp_servers/

# Copy scripts and codex workdir
COPY scripts/ scripts/
COPY codex_workdir/ /opt/codex_workdir/

# Initialize git repo in codex workdir (required by Codex CLI)
RUN cd /opt/codex_workdir \
    && git config --global user.email "sre-agent@local" \
    && git config --global user.name "SRE Agent" \
    && git init && git add -A && git commit -m "init"

# Place Codex config in ~/.codex/ (where Codex looks by default)
RUN mkdir -p /root/.codex \
    && cp /opt/codex_workdir/.codex/config.toml /root/.codex/config.toml

# SSH directory (config is mounted via docker-compose from agent/ssh_config)
RUN mkdir -p /root/.ssh && chmod 700 /root/.ssh

EXPOSE 8002

CMD ["uv", "run", "uvicorn", "agent.app.main:app", "--host", "0.0.0.0", "--port", "8002"]
