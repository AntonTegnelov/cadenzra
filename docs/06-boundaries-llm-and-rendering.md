# 06 — Boundaries: LLMs & Renderers

Cadenzra touches four external systems: a text-generation LLM, a multimodal audio-critique LLM, the LilyPond compiler, and the FluidSynth synthesizer. Each sits behind a `typing.Protocol` in `cadenzra/interfaces/`; concrete adapters live in their owning packages and are wired in one factory. Nothing in `graph/`, `verification/`, or `performance/` imports a vendor SDK or spawns a subprocess directly.

## The protocols

```python
class GeneratorLLM(Protocol):
    def derive_style_pack(self, spec: PieceSpec) -> StylePack: ...
    def plan_structure(self, spec: PieceSpec, style: StylePack) -> StructurePlan: ...
    def generate_motifs(self, briefs: list[MaterialBrief], ctx: MotifContext) -> MotifLibrary: ...
    def generate_harmony(self, ctx: HarmonyContext) -> HarmonicSkeleton: ...
    def generate_voice(self, ctx: VoiceContext) -> VoicePart: ...
    def review(self, question: ReviewRequest) -> ReviewVerdict: ...   # LLM validators

class AudioCritic(Protocol):
    def critique(self, audio: Path, brief: CritiqueBrief) -> CritiqueVerdict: ...

class ScoreRenderer(Protocol):
    def compile(self, lily_source: str, workdir: Path) -> CompileResult: ...
    # CompileResult: ok, pdf/midi paths, bar_check_warnings, raw compiler output

class Synthesizer(Protocol):
    def render(self, midi: Path, voices: list[VoiceSpec], out: Path) -> Path: ...

class FeedbackRouter(Protocol):
    def localize(self, verdict: CritiqueVerdict, plan: StructurePlan) -> list[FeedbackItem]: ...
```

Protocols express **musical intent, not transport** — `generate_voice`, not `complete_prompt`. Prompt construction is an implementation detail of the adapter, which means swapping providers (or inserting a fine-tuned model for one method only) is invisible above the boundary. Initial wiring: `ClaudeGenerator` implements `GeneratorLLM`, `GeminiCritic` implements `AudioCritic` and backs `FeedbackRouter.localize`; both SDKs are imported nowhere else.

`ScoreRenderer.compile` serving both fragment validation (scaffolded compiles) and final rendering is intentional — one boundary, one behavior, exercised constantly rather than only at the end of a run.

**Deliberately *not* a protocol: `interpret_performance`.** It is deterministic internal code (score MIDI + `InterpretationParams` → performance MIDI, in `performance/`), not an external system — there is no vendor to swap and no non-determinism to fake. Wrapping it in a protocol would be abstraction without a need; it is tested directly as a pure transform ([09](09-testing-and-milestones.md)).

## The musician-surface translation layer

The `llm` package is where the internal/surface split from [03](03-musical-representations.md) is implemented, and this placement is load-bearing:

- **`llm/prompts/`** renders internal state into the musician's view — offsets become bar/beat, `MeterSpec` becomes "7/8 (2+2+3)", `Pitch` becomes note names, motifs are inlined as verbatim notation, and capability gating decides which instructions the surface shows at all ([04](04-generation-layers.md)).
- **`llm/parsers/`** normalizes the musician's view back — bar/beat to offsets, note names to `Pitch` — and validates shape with Pydantic.

Because both directions of translation live in this one package, the two registers can evolve independently: changing an internal coordinate touches no prompt text; tuning a prompt surface (including empirically, via the live harness's A/B pass rates, [09](09-testing-and-milestones.md)) touches no internal type. No other package converts between registers — a bar number appearing in `verification/` logic, rather than in a rendered feedback message, is a review flag.

## Structured-output discipline

Every structured LLM result (`StylePack`, `StructurePlan`, `MotifLibrary`, `HarmonicSkeleton`, `ReviewVerdict`, `CritiqueVerdict`, router output) is produced via **forced tool calling** against a schema, parsed and Pydantic-validated in `llm/parsers/`, and nowhere else. Business code never sees raw model text. A response without a tool call, or one failing validation, raises `LLMOutputError` and is handled by the adapter's bounded retry (3 attempts, then raise) — never scraped with regex, never coerced to a default. A new LLM capability means four artifacts in the `llm` package: prompt builder in `prompts/`, schema in `schemas/`, parser in `parsers/`, method on the protocol.

**The LilyPond exception, precisely bounded.** `Motif.lily_music` and `VoicePart.lily_music` are free text by nature — wrapping notation deeper in JSON adds an escaping layer and no validation power, since JSON well-formedness says nothing about musical well-formedness. Fragments still arrive via tool call (schema: `{lily_music: string, lily_lyrics: string|null, techniques: [...]}`) so extraction is uniform, but their *real* validation is the compile-and-analyze path in [05](05-verification-and-feedback.md). Structured outputs guarantee shape; the compiler guarantees substance. Each guard exists exactly once, at the layer that can actually check it.

## Subprocess boundaries

LilyPond and FluidSynth are external programs and get full boundary treatment — the one place where defensive code is substance, not theater:

- Invocations run with explicit timeouts, in per-run scratch directories, with stdout/stderr captured in full.
- A non-zero exit or timeout raises a specific error (`LilypondCompileError`, `SynthesisError`) carrying the complete tool output — compiler stderr is *evidence* for feedback items and must survive to the log.
- `LilypondAdapter` owns the one gnarly parsing job at this boundary: extracting structured bar-check warnings (file, line, bar) from compiler stderr. That parsing lives in the adapter, tested against captured real outputs, and nowhere else.
- Version pinning: the adapter asserts the LilyPond major version at startup, because error-message formats (which we parse) and syntax defaults drift between releases. Fail at startup with a clear message, not mid-run with a mysterious parse failure.
- No retries for subprocesses: compilers are deterministic, so retrying an identical input is theater. Failures route back as feedback (bad input) or abort the run (environment problem) — the exit status plus warning content distinguishes the two.

LLM calls, by contrast, are non-deterministic and *do* warrant bounded retries on transport errors and malformed outputs — same boundary philosophy, different failure model, hence different handling.

## Configuration

One `RunConfig` (Pydantic settings) carries: model ids per role, retry budgets per loop, LilyPond/FluidSynth executable paths, SoundFont path(s), output directory, and the random seed for any stochastic choices (including any randomness the interpretation stage ever adopts — reproducible runs stay reproducible). The factory (`app/factory.py`) reads `RunConfig`, constructs adapters, and hands the graph builder a `Services` container of protocol implementations. Tests hand it fakes; nothing is patched.
