FROM python:3.12-slim

WORKDIR /app

# System deps: SSH server, diagnostic tools (top, df, ps, netstat, iostat, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server \
    curl \
    procps \
    net-tools \
    sysstat \
    stress-ng \
    && rm -rf /var/lib/apt/lists/*

# Configure SSH
RUN mkdir -p /var/run/sshd \
    && sed -i 's/#PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config \
    && sed -i 's/#PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config \
    && echo "PubkeyAuthentication yes" >> /etc/ssh/sshd_config

# Create sre-agent user (restricted)
RUN useradd -m -s /bin/bash sre-agent \
    && mkdir -p /home/sre-agent/.ssh \
    && chmod 700 /home/sre-agent/.ssh \
    && chown -R sre-agent:sre-agent /home/sre-agent/.ssh

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app and stress scripts
COPY app/ app/
COPY stress/ stress/
RUN chmod +x stress/*.sh

# Copy entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8090 22

CMD ["/entrypoint.sh"]
