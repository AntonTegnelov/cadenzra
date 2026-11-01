---
paths:
  - "**/*.py"
  - "**/pyproject.toml"
---
# Python conventions

**Rule:** Typed, modern (3.12+), `uv`-managed Python. `ruff format` and `ruff check` clean, the type checker (`mypy` or `ty`, whichever the project uses) clean, `pytest` green before any task is done.

**How to apply:**

### Types
- Type hints on every function signature and public attribute. `X | None`, never `Optional[X]`; built-in generics (`list[str]`, `dict[str, int]`), never `typing.List`.
- Data shapes are frozen dataclasses or Pydantic models, not bare dicts. Pydantic validates at boundaries (user input, deserialized JSON, LLM output); internal code passes the validated model onward without re-checking (see [[fail-loud]]).
- `typing.Protocol` for the interfaces of [[protocol-boundaries]]; constructor injection; concrete classes instantiated only in the composition root.
- `Literal` and `Enum` for closed sets; `TypedDict` with `NotRequired` for typed mappings you don't own.

### Errors
- A project error hierarchy rooted in one base class (`ProjectError`), one specific subclass per distinct failure. Catch specific classes; never bare `except` or `except Exception: pass`. The one sanctioned broad catch is around a vendor SDK call where any transport exception is a retryable external failure.
- `assert` is not error handling and ruff forbids it in `src/`; raise the specific exception.
- Context managers for every resource.

### Style
- Pure functions and immutable data by default (see [[separation-of-concerns]]). `@property` for read-only computed attributes.
- `logging` (structured where available), never `print`, for application output; the CLI layer is the only place that prints to the user.
- `asyncio` for I/O-bound concurrency; `await` vendor calls, don't wrap them in threads.
- Docstrings (Google style) on public modules, classes, and functions: purpose, args, returns, raises. Keep them honest and short.
- If an edit seems not to apply, `ruff` (or a pre-commit hook) formatted it back. Read the rule at https://docs.astral.sh/ruff/rules/ before retrying.

### Tests
- `pytest` with fixtures and `parametrize`. Strongly prefer integration tests over mock-heavy unit tests; fake at the Protocol boundary only. Never `monkeypatch` internals to make a test pass.
- Tests that need real keys or services are opt-in by marker (`local_only`, `integration`) and are skipped only by that marker, never by a missing prerequisite (see [[testing-discipline]]).
- Test through public interfaces; a private function that needs its own tests wants to be a public function of its own module.

### Environment
- `uv sync` / `uv run`; dependencies declared in `pyproject.toml` with pinned versions; never `pip install` ad hoc into the shared venv.
- The venv lives outside the bind mount in containers (`/home/dev/.venv`); when worktrees share it, run with `PYTHONPATH=<worktree>/src` and re-check installed versions against the lockfile before believing an import or mypy error (see [[devcontainer-environment]]).
