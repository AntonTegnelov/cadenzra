# Working inside the house dev container

**Rule:** Every project runs in an SSH-reachable Linux dev container (`/workspaces/<project>`, user `dev`). The container is the blast-radius boundary: it holds only this repo's credentials, and its state outside named volumes is disposable. Work inside it accordingly: keep caches and build output off the bind mount, never rebuild or recreate the container yourself, and reach GitHub only through the per-repo token already installed.

**Why:** The workspace is usually a 9p bind mount of a Windows drive: slow, sometimes nearly full, and it produces `Input/output error`, `ENOSPC`, and 0-byte files that look exactly like code bugs. Container recreation wipes the writable layer (past data loss: 2026-07-29), and an account-wide credential inside a container would defeat the isolation the containers exist for.

**How to apply:**

### Filesystem
- Build output, caches, venvs, and `node_modules` go on the named volumes the container provides, or under `/home/dev` (e.g. `CARGO_TARGET_DIR=$HOME/.cache/cargo-target/<project>`, `--store-dir /home/dev/.pnpm-store`), never on the bind mount. Worktrees under `.claude/worktrees/` are *not* volume-masked: build them in a detached worktree under `/home/dev` if the build is heavy.
- If a tool fails with disk I/O errors, writes empty files, or a cache database corrupts: run `df -h .` first. Tell the owner when the host drive is full; it is theirs, don't delete their files.
- Large scratch (snapshot extractions, screenshots, exports) goes under `/tmp` or the session scratchpad, not the checkout.
- The repo's own `.venv/` is the Windows one; the container's interpreter lives at `/home/dev/.venv` (or the toolchain volume). Verify `which python` / `which cargo` before trusting a "missing module" error.

### Git
- Host checks out with `core.autocrlf=true`; the container has it baked in. If every file shows modified with an empty `git diff --stat`, the fix is `git checkout -- <those files>`, never `git update-index -- <path>` (that stages the path).
- Untracked `.env` files may still carry CRLF: `source <(sed 's/\r$//' .env)` before sourcing in bash.
- Parallel sessions share one `.git` and often one venv: another session can repoint an editable install or change installed versions under you. Before debugging an import or type error that smells environmental, check installed versions against the lockfile and reinstall from it.
- IDE git integrations race for `.git/index.lock`; wait, don't delete (see [[delivery-flow]]).
- A container OOM can zero-fill files in `.git` (`fatal: bad config line 1`). Detect with `head -c 200 .git/config | cat -A`, rebuild the file from the remote's state, `git fsck --full`. Keep concurrent worktrees few (3 to 5 is already too many for most containers).

### Credentials and GitHub
- Git auth is a fine-grained per-repo PAT in the credential store (`~/.ssh/git-credentials`); `git push` over https just works. Never add an SSH key to the GitHub account, never request an account-wide token.
- For the GitHub API without `gh`: `printf 'protocol=https\nhost=github.com\n\n' | git credential fill`, take the `password=` line inside a script, pass it as a bearer header to `curl`, never print it. With an old `gh`, prefer `gh api` REST calls over `gh issue view` / `gh pr checks`, which fail on deprecated fields or PAT scope.
- Cross-repo actions (editing another repo's settings, pushing elsewhere) are the owner's, not yours.

### Container lifecycle
- Never `docker compose down`, rebuild, or recreate the container from inside a task. Key rotation is `docker compose restart` from the host. Anything installed after start that must survive goes on a named volume.
- The reference for the pattern, the port table, and per-language notes is `E:\Programmering\Code\DEVCONTAINER_TEMPLATE.md` on the host; read it before touching `.devcontainer/`.
