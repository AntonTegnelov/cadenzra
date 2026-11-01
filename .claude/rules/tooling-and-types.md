# Explicit types, strict tooling, clean before done

**Rule:** Types are explicit and strict; the project's formatter, linter, and type checker are run and clean before any task is called done; warnings are treated as errors. Dependencies are added deliberately, pinned, and justified.

**Why:** The compiler and the type checker are the cheapest reviewers the project has; they catch whole classes of bugs before a test is written and make [[fail-loud]] possible (you can only trust internal types if they are actually enforced). Lint and format noise in a diff hides the real change. Every dependency is attack surface, build time, and upgrade burden.

**How to apply:**

### Types
- Annotate every function signature, public field, and non-obvious binding. Avoid `any`, untyped `object`, bare `dict`, and inference that hides the shape of data.
- Represent validated data with types: newtypes, enums, discriminated unions, frozen models. Parse at the boundary into a typed value; never pass raw dicts or strings inward (see [[fail-loud]]).
- Nullability is explicit in the type (`T | None`, `Option<T>`, `T?`, `Optional<T>`); non-nullable means non-nullable and is not re-checked.
- Use the language's idiomatic error type (`Result`, specific exception classes, checked exceptions where the language has them). Define a project-level error hierarchy; never signal errors through return codes, globals, or `None`.

### Tooling
- Learn the project's commands from `CLAUDE.md` and run them: format, lint, type-check, test. Fix every warning, or explicitly and consciously allow it with a comment stating why.
- If your edit seems not to apply, an auto-formatter or a pre-commit hook probably rewrote it back. Read the tool's rule before fighting it.
- Configure linters for maximum strictness the project can bear; don't loosen a rule to make a diff pass.
- Use the project's logging framework, never `print`/`console.log`/`System.out` for application logging. Log at the boundary with context (ids, counts, durations), structured where the project supports it.

### Dependencies
- Prefer the standard library, then a library already in the project, then a new dependency, in that order. Adding one is a stated decision with a reason.
- Choose mature, maintained libraries; pin versions; prefer stable over bleeding-edge.
- Never pull in a dependency whose license conflicts with the project's license. If linking it is requested anyway, explain the tradeoff and get explicit confirmation first.
- Use the project's package manager and lockfile (`uv`, `cargo`, `pnpm`/`bun`, `gradle`, `dotnet`); never install things ad hoc outside it.
