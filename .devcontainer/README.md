# resume_manager dev container

An SSH-reachable Linux dev box for resume_manager, following the same pattern
as the other projects in this folder (vetdux 2222, quirefold 2223,
vetdux_marketing 2224, tallynix 2225 — **this one uses port 2226**).

## What's inside

| Tool | Version / notes |
|---|---|
| Python | 3.13 (`python:3.13-slim-bookworm` base), venv at `/home/dev/.venv` on PATH |
| TeX Live | xelatex + fontspec, fontawesome5, titlesec, Swedish babel, Lato font |
| Node.js | 20 (NodeSource) |
| Claude Code | latest, installed globally via npm |
| Scraper browser deps | Xvfb + Firefox runtime libs (`playwright install-deps firefox`) + libegl1, for the `linkedin_scraper` track's stealth Firefox |
| sshd | hardened: pubkey-only, no root, `dev` user only, host port **2226** |

The repo is bind-mounted at `/workspaces/resume_manager`, so edits sync both
ways. The gitignored `.env` (Gemini API key) arrives via the mount — it is
never baked into the image (`.dockerignore` keeps it out of the build context).

## One-time setup

Make sure `%USERPROFILE%\.ssh\authorized_keys` on the host contains your
public key:

```
type %USERPROFILE%\.ssh\id_ed25519.pub >> %USERPROFILE%\.ssh\authorized_keys
```

The entrypoint installs this file into the container on every start, so key
changes only need `docker compose restart` — no rebuild.

## Build and start

```
docker compose -f .devcontainer/docker-compose.yml up -d --build
```

The first build downloads ~2 GB of TeX Live packages; later rebuilds reuse the
cached layer. The container auto-restarts with Docker Desktop
(`restart: unless-stopped`).

Stop: `docker compose -f .devcontainer/docker-compose.yml down`
(add `-v` to also wipe the Claude login and ssh host keys).

## Connect

Add to `~/.ssh/config` on the host:

```
Host resume-manager-dev
    HostName localhost
    Port 2226
    User dev
```

Then `ssh resume-manager-dev`, or point Claude Code Desktop / Cursor /
JetBrains Gateway at it. VS Code users can instead use
"Dev Containers: Reopen in Container", which runs the project setup
automatically via `postCreateCommand`.

## First-login project setup (SSH users)

```bash
cd /workspaces/resume_manager
pip install -e '.[dev]'
pre-commit install || test -x .git/hooks/pre-commit
```

(`pre-commit install` writes the hook, then fails on a final `chmod` — a
Docker Desktop bind-mount quirk where files are root-owned. The mount is
world-executable, so the hook works; the `test -x` fallback confirms it.)

`pip`/`python` resolve to the container venv at `/home/dev/.venv` (it's first
on PATH via `/etc/environment`). The repo's `.venv/` directory is the
**Windows** venv — never use it in the container. Sanity check:
`which python` must print `/home/dev/.venv/bin/python`.

## Claude Code

`claude` is preinstalled. Log in once (`claude` → follow the OAuth flow);
credentials live on the `claude-config` named volume and survive rebuilds.

## Troubleshooting

- **`Permission denied (publickey)`** — check `%USERPROFILE%\.ssh\authorized_keys`
  contains your pubkey, then `docker compose -f .devcontainer/docker-compose.yml restart`.
- **Host key changed after `down -v`** — the host-key volume was wiped; run
  `ssh-keygen -R "[localhost]:2226"` on the host and reconnect.
- **xelatex missing-font errors** — `fc-list | grep -i lato` should list Lato;
  `kpsewhich fontawesome5.sty` should resolve.
- **`resume-manager: command not found`** — run the first-login setup above;
  the editable install lives in the container venv, not the image.
