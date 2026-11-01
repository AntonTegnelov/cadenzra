# Security is real controls at real boundaries; secrets and personal data never enter the repo

**Rule:** Validate untrusted input at the boundary, represent validated data with types, and map every security control to a concrete threat. Secrets, credentials, and personal data live outside version control and outside the code, always.

**Why:** A breach or a leaked credential is unrecoverable in a way a bug is not. Personal data in a git history can't be un-published. And the agent doing the work runs with whatever credentials are in reach, so the credentials in reach must be the minimum the task needs.

**How to apply:**

### Boundaries
- Zero trust at the boundary: API requests, CLI args, files, LLM output, webhooks. Validate once, at entry, into a typed value; internal code trusts it from there (see [[fail-loud]]).
- Never build SQL, shell commands, or query strings by concatenating untrusted input. Parameterized queries and argument arrays only.
- Never leak internal state (raw SQL errors, stack traces, file paths) in responses to clients. Map internal errors to sanitized external ones at the edge; log the detail server-side.
- Sensitive logic stays server-side. Client code renders and validates for UX; the server decides.
- Stay in safe code: no `unsafe`, no `eval`, no disabling TLS verification, no `dangerouslySetInnerHTML` without a stated reason and review.

### Secrets
- Secrets come from environment variables or a secrets manager at runtime, never from source, never from a committed config file. `.env` files are gitignored and reach containers only via mount.
- Never log a secret, token, or key. Never print one to find it; use the credential helper or the SDK's own lookup.
- The environment an agent runs in holds only credentials scoped to that project (per-repo tokens, per-project service accounts, read-only where possible). Never request, add, or use an admin or account-wide credential from inside a project environment; never manipulate repo settings, branch protection, workflows-as-privilege, or IAM from it.

### Personal data
- Real personal data (names, phones, addresses, CVs, chat transcripts, customer records) never enters a commit. Local data directories are gitignored and root-anchored; tests use sanitized stand-ins under `tests/fixtures/`.
- Treat any personal value appearing in a diff as a bug. Never weaken a gitignore rule that protects such a directory.
- Config files with real business data (`config/*.json`) are user data, not code: gitignored, with a clearly named `*.example.json` committed instead.
- Legal and compliance documents are not engineering artifacts: don't edit them; record discrepancies in a companion addendum for the owner to decide on.

### Theater check
- Every control must answer "which attack does this stop, and can that attack happen here?" A control with no threat behind it is security theater and is cut (see [[substance-over-theater]]). A control with a real threat behind it (rate limits, no-probe hosts, mTLS at the origin) is enforced at the point where the traffic actually leaves or enters, not with a check a refactor can slip past.
