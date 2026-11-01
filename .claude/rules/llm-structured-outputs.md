# LLM calls return structured data, parsed in one place, judged by their consumer

**Rule:** Every LLM invocation goes through the project's LLM interface (see [[protocol-boundaries]]) and returns structured output via forced tool calling or a structured-output schema. The result is normalized into internal types in exactly one parsing package. Business and pipeline code never sees raw model text and never parses it.

**Why:** Structured outputs are validated before they reach the pipeline. You get typed access, and the failure mode is a clean `LLMOutputError` handled by a bounded retry, instead of a half-parsed dict propagating into an artifact the human downstream will trust. Keeping all parsing in one place means prompt or schema drift breaks in one visible spot.

**How to apply:**
- A new LLM capability is always the full set of pieces: a prompt builder, a tool/output schema, a parser, and a method on the interface implemented by the vendor adapter. No shortcuts that skip the parser.
- Parsers validate (Pydantic or equivalent) and raise one error type on anything missing or unrecognizable. They **never** return a coerced default (see [[fail-loud]]). One error type, deliberately: a split with no criterion ends up meaningless.
- No `json.loads`, regex extraction, or "find the JSON in the text" anywhere. Tool calling is forced, so a reply without a tool call is an error handled by the retry loop, not something to scrape.
- No prompt text saying "respond with JSON matching this schema"; the structured-output machinery handles that.
- Parsers judge *shape*, not *content*. Whether the output is good is decided by the deterministic validators, the compiler, or the tests downstream; duplicating that in the parser is the same guard in two places. The surface may be forgiving (normalize a wrapper), never inventive (default a missing field).
- Show the model only what the task needs: gate optional schema fields by capability rather than exposing everything always.
- Prompts speak the model's competent surface (domain language the model knows), not the system's internal representation; the translation happens in the prompt builder and the parser and nowhere else.
- **Layers that retry must feed their rejection reasons into the next prompt.** A retry that resends an identical prompt produces the same mistake rephrased until the budget runs out. Write a test asserting the feedback reaches the prompt.
- Retry the non-deterministic vendor call with bounded attempts and backoff; do not retry deterministic downstream tools. When the budget runs out, fail the run non-zero with everything produced so far preserved. Never pad, trim, or drop to force completion.
- Never paraphrase a compiler or validator failure in the feedback; quote it. A summarized diagnosis sends the regeneration looking in the wrong place.
- **Do not give an LLM judge the answer key.** A critic or reviewer told what the piece was trying to be reports seeing that whether or not it is there. Brief judges blind.
- Reasoning and internal fields are English; only user-facing free-text fields are localized, via a language instruction parameter on the prompt builder, never per-language prompt forks.
- Model tiering is explicit and pinned by a test: the fast tier only for calls that read one document and return facts or a choice from a supplied list; the strong tier by default; the top tier only by explicit promotion.
- Re-running a whole pipeline to see one call differently is the most expensive habit an LLM project can have. Log every call with its prompt, schema, and response, and provide a replay tool that fires one logged turn against the current code for the price of one call. Escalate replay, resume, full run, in that order.
