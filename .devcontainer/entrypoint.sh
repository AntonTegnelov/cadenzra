#!/bin/sh
# Entrypoint for the cadenzra dev container.
# Runs under tini (compose init: true). Installs authorized_keys from the
# host bind mount, generates persistent host keys, then execs sshd.
set -eu

# Generate missing host keys into the persistent volume at /etc/ssh/keys.
# Idempotent: only types that don't already exist are created, so the
# fingerprint stays stable across `docker compose down/up` cycles.
mkdir -p /etc/ssh/keys
chmod 700 /etc/ssh/keys
for type in rsa ecdsa ed25519; do
    key="/etc/ssh/keys/ssh_host_${type}_key"
    if [ ! -f "$key" ]; then
        ssh-keygen -q -t "$type" -N '' -f "$key"
    fi
done
chmod 600 /etc/ssh/keys/ssh_host_*_key
chmod 644 /etc/ssh/keys/ssh_host_*_key.pub

# Install authorized_keys from the read-only host mount; strip CRLF in case
# the host file was saved by a Windows editor. Runs on every start, so key
# changes only need a container restart — no rebuild.
if [ -s /tmp/host_authorized_keys ]; then
    install -d -m 700 -o dev -g dev /home/dev/.ssh
    tr -d '\r' < /tmp/host_authorized_keys > /home/dev/.ssh/authorized_keys
    chown dev:dev /home/dev/.ssh/authorized_keys
    chmod 600 /home/dev/.ssh/authorized_keys
else
    echo "WARNING: /tmp/host_authorized_keys missing/empty - SSH login will fail." >&2
    echo "         Populate %USERPROFILE%\\.ssh\\authorized_keys and restart the container." >&2
fi

# Self-heal ownership of the claude-config named volume (can be root-owned
# if the volume was created before the image pre-created the dir).
chown dev:dev /home/dev/.claude
chmod 0755 /home/dev/.claude

exec /usr/sbin/sshd -D -e
