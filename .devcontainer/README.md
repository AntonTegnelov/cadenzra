# cadenzra dev container

An SSH-reachable Linux dev box carrying the whole toolchain, exposed on host
port **2227**.

## What's inside

| Tool | Version / notes |
|---|---|
| Python | 3.14 (`python:3.14-slim-bookworm` base), venv at `/home/dev/.venv` on PATH |
| LilyPond | 2.26.0, pinned — its error-message format is parsed by `rendering/lilypond.py`, so bumping it means regenerating the captured-stderr fixtures (docs/09) |
| FluidSynth | 2.5.7, built from source with libsndfile for `-F` WAV rendering |
| SoundFont | Debian's `fluid-soundfont-gm` (General MIDI) |
| uv | targets the container venv (`UV_PROJECT_ENVIRONMENT=/home/dev/.venv`) |
| Node.js | 20 (NodeSource) |
| Claude Code | latest, installed globally via npm |
| sshd | hardened: pubkey-only, no root, `dev` user only, host port **2227** |

The repo is bind-mounted at `/workspaces/cadenzra`, so edits sync both ways.
The gitignored `.env` (Gemini API key) arrives via the mount — it is never
baked into the image (`.dockerignore` keeps it out of the build context).

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

The first build compiles FluidSynth from source and downloads LilyPond; later
rebuilds reuse the cached layers. The container auto-restarts with Docker
Desktop (`restart: unless-stopped`).

Stop: `docker compose -f .devcontainer/docker-compose.yml down`
(add `-v` to also wipe the persistent home volume and ssh host keys).

## Connect

Add to `~/.ssh/config` on the host:

```
Host cadenzra-dev
    HostName localhost
    Port 2227
    User dev
```

Then `ssh cadenzra-dev`, or point Claude Code Desktop / Cursor /
JetBrains Gateway at it. VS Code users can instead use
"Dev Containers: Reopen in Container", which runs `uv sync` automatically via
`postCreateCommand`.

## First-login project setup (SSH users)

```bash
cd /workspaces/cadenzra
uv sync --dev
```

`pip`/`python` resolve to the container venv at `/home/dev/.venv` (it's first
on PATH via `/etc/environment`). A `.venv/` directory in the repo is a
**host-side** venv — never use it in the container. Sanity check:
`which python` must print `/home/dev/.venv/bin/python`.

## Claude Code

`claude` is preinstalled. Log in once (`claude` → follow the OAuth flow);
credentials live on the persistent `home` volume and survive rebuilds.

## Troubleshooting

- **`Permission denied (publickey)`** — check `%USERPROFILE%\.ssh\authorized_keys`
  contains your pubkey, then `docker compose -f .devcontainer/docker-compose.yml restart`.
- **Host key changed after `down -v`** — the host-key volume was wiped; run
  `ssh-keygen -R "[localhost]:2227"` on the host and reconnect.
- **`cadenzra: command not found`** — run `uv sync --dev`; the editable
  install lives in the container venv, not the image.
- **LilyPond version assertion fails at startup** — the adapter pins the major
  version (docs/06); rebuild the container rather than pointing at a system
  LilyPond.
