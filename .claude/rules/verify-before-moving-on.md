# One task at a time, verified before the next

**Rule:** When working a TODO or any list of tasks, do one task at a time and verify it actually works — ideally with a test — before starting the next. Only bundle tasks that are literally inseparable (genuinely tied together). Finishing and confirming each step beats building everything at once.

**Why:** When you build several things before verifying any of them, a failure could be in any of them, and you debug a pile instead of a step. Verifying as you go keeps every failure localized and cheap to find. A little rework when a later task forces a small change to an earlier one is far cheaper than a big-bang integration that doesn't work and gives no clue why. It also keeps the working state honest — you always know exactly how far you actually got.

**How to apply:**
- Sequence: complete a task → verify it (run the test, run the code, exercise the path) → only then start the next.
- Keep each unit modular and extensible so the next task slots in cleanly — but do **not** pre-build machinery for tasks you haven't started yet (that's speculation; see [[right-sized-abstraction]]).
- Prefer a test as the verification, written in the spirit of [[tdd-mindset]] — pinning the contract the task was supposed to satisfy.
- If a task genuinely can't be verified right now (e.g. it needs an environment or credential that isn't available), say so explicitly and mark it unverified — don't quietly assume it works and move on.
- When you discover adjacent work mid-task, note it as its own task rather than expanding the current one.
