# syntax=docker/dockerfile:1.6
FROM python:3.14-slim-bookworm

ARG NODE_MAJOR=20
ARG DEV_USER=dev
ARG DEV_UID=1000
ARG DEV_GID=1000

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8

# ---- Base packages ----------------------------------------------------------
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg xz-utils \
        git build-essential \
        ripgrep fd-find less vim \
        openssh-server sudo \
        locales tini fontconfig \
 && sed -i '/en_US.UTF-8/s/^# //' /etc/locale.gen && locale-gen \
 && rm -rf /var/lib/apt/lists/*

# fd is installed as `fdfind` on Debian; provide the conventional `fd` alias.
RUN ln -s /usr/bin/fdfind /usr/local/bin/fd

# ---- Node.js (NodeSource) + Claude Code -------------------------------------
RUN curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/* \
 && npm install -g @anthropic-ai/claude-code \
 && npm cache clean --force

# ---- Dev user ---------------------------------------------------------------
RUN groupadd --gid "${DEV_GID}" "${DEV_USER}" \
 && useradd  --uid "${DEV_UID}" --gid "${DEV_GID}" --create-home --shell /bin/bash "${DEV_USER}" \
 && echo "${DEV_USER} ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/${DEV_USER}" \
 && chmod 0440 "/etc/sudoers.d/${DEV_USER}" \
 && install -d -m 0700 -o "${DEV_USER}" -g "${DEV_USER}" "/home/${DEV_USER}/.ssh" \
 && install -d -m 0755 -o "${DEV_USER}" -g "${DEV_USER}" \
        "/home/${DEV_USER}/.cache" "/home/${DEV_USER}/.local" \
        "/home/${DEV_USER}/.config" "/home/${DEV_USER}/.claude"

# ---- uv + container venv (NEVER the Windows .venv in the repo) --------------
RUN pip install --no-cache-dir uv \
    && python -m venv /home/${DEV_USER}/.venv \
    && chown -R ${DEV_UID}:${DEV_GID} /home/${DEV_USER}/.venv

# uv must target the container venv, not create .venv/ on the bind mount.
ENV PATH="/home/dev/.venv/bin:${PATH}" \
    VIRTUAL_ENV="/home/dev/.venv" \
    UV_PROJECT_ENVIRONMENT="/home/dev/.venv"

# ---- Env for sshd/PAM login shells ------------------------------------------
# Docker ENV does not propagate into ssh sessions; PAM reads /etc/environment.
# PATH must keep the system dirs or ssh logins lose git, etc.
RUN printf '%s\n' \
        'PATH="/home/dev/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"' \
        'VIRTUAL_ENV="/home/dev/.venv"' \
        'UV_PROJECT_ENVIRONMENT="/home/dev/.venv"' \
        'LANG="en_US.UTF-8"' \
        >> /etc/environment

# ---- SSH server -------------------------------------------------------------
# Hardened sshd config (pubkey-only, no root, dev user only).
COPY --chmod=0644 .devcontainer/sshd_config /etc/ssh/sshd_config.d/00-dev.conf

# Privilege separation directory required by sshd.
RUN install -d -m 0755 /var/run/sshd

# Entrypoint: install authorized_keys, generate host keys, exec sshd.
COPY --chmod=0755 .devcontainer/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh

# The repo is bind-mounted with host ownership; without this git refuses to
# operate ("dubious ownership") for both SSH and VS Code sessions.
RUN git config --system --add safe.directory /workspaces/cadenzra

WORKDIR /workspaces/cadenzra
EXPOSE 22

# tini is provided by docker-compose's `init: true`, which runs it as PID 1.
# Don't wrap with another tini here or you get nested-tini warnings and
# broken signal handling.
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
