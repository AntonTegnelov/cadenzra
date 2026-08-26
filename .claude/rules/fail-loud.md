# Fail loud; no fallbacks for impossible states

**Rule:** If a state is supposed to be impossible under the codebase's invariants, let it crash. Don't add `.get(default)`, `try/except Exception`, or coerced defaults to mask it. Conversely, for failures *outside* our control — the Gemini API, the LilyPond and FluidSynth subprocesses, files on disk — specific exceptions, bounded retries where the failure is non-deterministic, and user-facing error reporting are appropriate. The rule is about not hiding our own bugs, not about treating external systems as infallible.

**Why:** Defensive code hides real bugs. A silent fallback over an internal invariant turns "the invariant is broken" (loud, fixable in test) into "the score contains plausible-looking but wrong music" (quiet, catastrophic — the human downstream trusts the artifact; preventing exactly that output is why this system exists, per CLAUDE.md). But the same defensive instinct applied at a genuine system boundary is correct — the Gemini API *will* return malformed output sometimes, and crashing the whole run over a transient blip is a worse failure mode than a bounded retry plus a clear error.

**How to apply:**

### Inside our code — fail loud
- Use direct dict lookups (`d[key]`) and direct attribute access when the value is guaranteed by the type system or a prior validation step (e.g. values already parsed into frozen models like `VoicePart` or `StructurePlan` by `llm/parsers/`).
- Internal function-to-function calls trust their types. No re-checking what the type system already guarantees — mypy runs in CI for exactly this reason.
- If you catch an exception inside our code, catch a specific `CadenzraError` subclass and handle it meaningfully. Bare `except` or `except Exception: pass` is a red flag. (The one sanctioned broad catch is around the vendor call in `GeminiClient.call_tool`, where any transport exception is a retryable external failure.)
- When you see yourself writing "this probably can't happen but just in case," stop and either prove it can or remove the guard. A test should trip it before the bug ships.

### At system boundaries — retry where it's substance, and surface failure
- Validate at system boundaries: the piece spec, LLM responses (in `llm/parsers/`), subprocess output, MIDI read back from disk. These are exactly where invariants don't hold.
- Retry only what is non-deterministic. `GeminiClient.call_tool` is the pattern: bounded attempts, then `LLMOutputError` — no silent continuation with a fabricated value. LilyPond and FluidSynth are deterministic; retrying them is theater — they fail once, loudly, as `LilypondCompileError` / `SynthesisError` carrying the *complete* tool output.
- Never paraphrase a compiler failure. The raw stderr is the evidence a feedback item and the run log need; a summarized diagnosis sends the regeneration looking in the wrong place (CLAUDE.md: "quote the compiler").
- When a retry budget runs out: raise `BudgetExhaustedError` (or the appropriate subclass from `common/errors.py`), let the CLI catch it, and end the run non-zero with everything produced so far written to the output directory. Do *not* pad a bar, transpose away a range violation, or drop a section to force completion.
- "Fail loud" for an external dependency means **fail visibly to the user** (log + specific exception + non-zero exit), not necessarily an unhandled traceback. Anything that escapes `CadenzraError` *should* be an unhandled traceback — that's a bug surfacing, on purpose (`common/errors.py` docstring).
- The distinction is intent: are we hiding *our own* faulty code (no — fix it in test), or are we handling a genuinely uncontrolled failure mode (yes — validate, retry if non-deterministic, surface)?
