# Replay one turn before re-running a piece

**Rule:** When debugging a failed turn or experimenting with schemas, models, or prompts, reach for `uv run cadenzra replay <spec> <run-ts> <seq>` before `uv run cadenzra compose`. A full compose is the last step that confirms a fix end-to-end, never the first step that finds it.

**Why:** The cost audit measured 79.5% of all API spend going to re-runs of specs already attempted — most of which existed to evaluate one changed turn. A forty-minute, full-price piece to see one call differently is the single most expensive habit this project has had. Replay fires the logged prompt against the *current* schema and model wiring for the price of one call, into its own run dir, with `purpose: "replay"` in the log.

**How to apply:**
- **Find the seq** in `out/<spec>/runs/<run-ts>/` — `narrative.md` headings read `## <seq>. <label> — <section>/<voice>`, or grep `llm.jsonl` for the label/error. Failed attempts are logged too; those are usually the turns worth replaying.
- **What replay tests as-is:** schema changes (rebuilt by tool name from `llm/schemas/registry.py`), parser behavior against a real payload, model tiering (`CAPABILITY_MODELS` in `.env` — replay uses the same wiring as a live run), and plain nondeterminism ("does this turn fail every time or one time in three?").
- **What it does not rebuild: the prompt.** Replay fires the *logged* prompt verbatim — a change to a prompt builder in `llm/prompts/` is invisible to it. To experiment with prompt text, copy the run dir (or edit the stored `user_prompt`/`system_prompt` in the copy's `llm.jsonl`), edit the prompt, and replay that seq — an honest A/B for the price of two calls. Never edit the original run's log; it is the historical record.
- **Escalation order:** replay the turn → if the fix holds, `compose <spec> --resume` (skips every layer the previous run already paid for) → full `compose <spec>` only when scaffolding itself must regenerate. Each step up multiplies cost roughly tenfold.
- Replay needs the run's `state.json` for state-shaped schemas (`write_harmony`, `plan_lyrics`, `write_lyrics`); runs since 2026-08-10 keep their own copy in the run dir. It refuses loudly when the slice is gone — that refusal means "this turn needs a live pipeline", not "work around it".
- A replay is a real, billed API call under the `.env` models. It is cheap, not free — batch your hypotheses before firing, the way you would at a debugger breakpoint.
