# Read the codebase and its docs before adding anything

**Rule:** Before adding a module, file, function, dependency, or pattern, read the existing code and docs rigorously enough to know whether something already does the job or could be extended to. Reuse and follow the patterns the codebase already sets. A good structure is paramount; a second copy of an existing thing is a defect.

**Why:** Most "new" code in a mature project duplicates something that already exists under a different name. Duplicates drift, and the drift becomes the bug. The docs record intent that the code alone doesn't show, and the tests record the contract the author had in mind.

**How to apply:**
- Start from the project's `CLAUDE.md` and its documented entry points (`docs/README.md`, architecture and design docs, `docs/TODO.md`). Read the doc that covers the area you are about to change.
- Search before you create: the same concept may exist under another name, in a sibling package, or in a shared/common module. Check the tests to understand the intended behaviour.
- Follow existing conventions for naming, layout, error types, logging, and configuration. Consistency beats local preference.
- Prefer the chosen technologies and libraries of the project over new ones; adding a dependency is a decision that gets stated with its reason (see [[tooling-and-types]]).
- If the existing structure is wrong for the change, say so and propose the refactor as its own task (see [[critical-pushback]], [[right-sized-abstraction]]); don't bolt a parallel structure on beside it.
- Respect recorded decisions: if a doc, issue, or memory says an approach was evaluated and rejected, don't re-propose it unprompted.
- Configuration and data files are not code: no logic, computed fields, or commentary in them. Derive derived values in code.
