# One purpose per unit, named for exactly what it does

**Rule:** A function or class has a single purpose, and its name says what that purpose is. Prefer pure functions — return new data rather than mutating in place — wherever it's practical. This is not strict functional programming; it's keeping responsibilities from tangling. Split a unit as it grows or takes on responsibilities its name doesn't cover.

**Why:** A function that does several unrelated things hides what it does, can't be tested in isolation, and can't be reused. Naming a unit for its single job makes the call site read like a description of the program, and makes the wrong behavior obvious — if the honest name would need an "and", the code is doing too much. Pure functions are the easiest of all to test and reason about because their output depends only on their input.

**How to apply:**
- Name a function by exactly what it does, nothing more. If the truthful name is `process_and_store`, that's the signal to split it into `process` and `store` behind a thin orchestrator:
  ```python
  def handle_request(data):
      processed = process_data(data)
      store_data(processed)
  ```
  where `process_data` returns new data (pure) and `store_data` owns the side effect. The orchestrator's one job is sequencing.
- Short, trivially-related steps can live in one function if the name stays honest. The longer a function gets and the more separate things it does, the stronger the pull to refactor — let length and responsibility-count, not a fixed line limit, trigger the split.
- Push side effects (I/O, DB, network) to the edges; keep the core logic pure so it's testable without mocks. External side effects belong behind a boundary — see [[protocol-boundaries]].
- Splitting for its own sake can overshoot into premature abstraction — let [[right-sized-abstraction]] gate how far you factor.
