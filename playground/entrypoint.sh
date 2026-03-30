#!/bin/bash
set -e

# Generate SSH host keys if not exist
if [ ! -f /etc/ssh/ssh_host_ed25519_key ]; then
    ssh-keygen -A
fi

# Generate SSH keypair for sre-agent if keys volume is empty
SSH_DIR="/home/sre-agent/.ssh"
if [ ! -f "$SSH_DIR/id_ed25519" ]; then
    echo "Generating SSH keypair for sre-agent..."
    ssh-keygen -t ed25519 -f "$SSH_DIR/id_ed25519" -N "" -C "sre-agent@playground"
    cat "$SSH_DIR/id_ed25519.pub" > "$SSH_DIR/authorized_keys"
    chmod 600 "$SSH_DIR/authorized_keys" "$SSH_DIR/id_ed25519"
    chmod 644 "$SSH_DIR/id_ed25519.pub"
    chown -R sre-agent:sre-agent "$SSH_DIR"
    echo "SSH keypair generated."
elif [ ! -f "$SSH_DIR/authorized_keys" ]; then
    # Keys exist (from volume) but authorized_keys not set
    cat "$SSH_DIR/id_ed25519.pub" > "$SSH_DIR/authorized_keys"
    chmod 600 "$SSH_DIR/authorized_keys"
    chown sre-agent:sre-agent "$SSH_DIR/authorized_keys"
fi

# Start SSH daemon
echo "Starting SSH daemon..."
/usr/sbin/sshd

echo "Starting Playground app on :8090..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8090
