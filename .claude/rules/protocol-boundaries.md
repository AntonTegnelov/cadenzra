# External systems sit behind Protocols

**Rule:** Every external system or swappable backend — the generator LLM, the audio critic, the LilyPond compiler, the FluidSynth synthesizer — is accessed through a `typing.Protocol` defined in `src/cadenzra/interfaces/`. Concrete implementations live in their owning domain package and are wired together in `app/factory.py` (`build_services`), the only module that knows which concrete class implements which protocol.

**Why:** Pipeline and graph code should not know whether the composer is Gemini or a test fake, or whether "compile" means a real `lilypond` subprocess. Because the graph depends on `GeneratorLLM` and `ScoreRenderer`, swapping an implementation is a single edit in the factory, and tests hand fakes through that same door — nothing is ever patched (docs/06, docs/07).

**How to apply:**
- When adding a new external dependency, define the Protocol in `interfaces/` first, then write the impl in its domain package, then wire it in `app/factory.py`.
- Never import `google.genai` (or any vendor SDK) outside `llm/clients/`. Graph nodes, validators, and CLI commands see only the protocols.
- Protocols express musical intent (`generate_voice`, `critique`, `compile`), never transport (`complete_prompt`, `post_json`). Prompt construction is an implementation detail of the adapter — that's what makes swapping providers, or slotting a fine-tuned model into one method, invisible above the boundary (docs/06).
- If you need to inspect a concrete type in pipeline code, that's a signal the Protocol is wrong — extend the Protocol instead of downcasting.
- Protocols mark *genuine externality* — a vendor or binary that tests must replace — not "things that feel important" (docs/08). The interpretation transform deliberately has no protocol: it's deterministic internal code with nothing to swap and no non-determinism to fake. Don't add a protocol for code like that.
- A single-consumer implementation lives inside its own domain package — `GeminiGenerator` under `llm/services/`, `LilypondAdapter` under `rendering/` — not in a shared "integrations" area.
- References: `interfaces/llm.py` (`GeneratorLLM`) → `llm/services/gemini_generator.py`; `interfaces/critique.py` (`AudioCritic`, `FeedbackRouter`) → `llm/services/gemini_critic.py`; `interfaces/rendering.py` (`ScoreRenderer`, `Synthesizer`) → `rendering/lilypond.py`, `rendering/fluidsynth.py`; wiring in `app/factory.py`.
