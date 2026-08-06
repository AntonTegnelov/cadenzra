# 07 — Project Structure

## Repository layout

```
cadenzra/
├── pyproject.toml                  # uv-managed; py3.14; pydantic, langgraph, mido
├── docs/                           # this documentation
├── src/cadenzra/
│   ├── interfaces/                 # ALL Protocols (GeneratorLLM, AudioCritic,
│   │                               #   ScoreRenderer, Synthesizer, FeedbackRouter)
│   ├── model/                      # pure data: PieceSpec, StylePack, StructurePlan,
│   │                               #   MotifLibrary, HarmonicSkeleton, VoicePart,
│   │                               #   InterpretationParams, FeedbackItem,
│   │                               #   PipelineState; foundational types (Pitch,
│   │                               #   MeterSpec, time helpers) in model/primitives/
│   ├── llm/                        # ── the musician-surface translation layer ──
│   │   ├── clients/                # vendor SDK imports live here and only here
│   │   ├── prompts/                # internal → surface: prompt builders, surface
│   │   │                           #   rendering (bar/beat, meter strings, gating)
│   │   ├── schemas/                # tool-call schemas (surface-shaped)
│   │   ├── parsers/                # surface → internal: the only place LLM output
│   │   │                           #   is parsed/validated/normalized
│   │   └── services/               # ClaudeGenerator, GeminiCritic (implement protocols)
│   ├── notation/
│   │   ├── assemble.py             # pure: fragments + plan → section/score LilyPond;
│   │   │                           #   owns the one-voice-one-channel invariant
│   │   ├── scaffold.py             # pure: fragment → minimal compilable wrapper
│   │   └── chords.py               # pure: chord-symbol → pitch-class set (12-EDO view)
│   ├── rendering/
│   │   ├── lilypond.py             # LilypondAdapter (subprocess, stderr parsing)
│   │   └── fluidsynth.py           # FluidsynthAdapter (subprocess)
│   ├── performance/                # ── the performance domain (no LLM, no subprocess) ──
│   │   ├── interpret.py            # pure: score MIDI + InterpretationParams
│   │   │                           #   → performance MIDI
│   │   └── curves.py               # pure: DynamicsPlan → CC curve events
│   ├── verification/
│   │   ├── midi_analysis.py        # pure: mido track data → notes/onsets per voice
│   │   ├── transposition.py        # pure: interval-sequence relations for motif
│   │   │                           #   entries (exact + "tonal answer" tolerance)
│   │   ├── structure.py            # one module per validator; pure logic,
│   │   ├── motifs.py               #   services injected for compile/LLM review
│   │   ├── harmony.py
│   │   ├── voice.py
│   │   ├── section.py
│   │   └── score.py
│   ├── graph/
│   │   ├── nodes.py                # thin node functions: unpack state, call
│   │   │                           #   generation/verification/performance,
│   │   │                           #   return updates
│   │   └── build.py                # ALL LangGraph wiring: edges, conditional
│   │                               #   skip (motifs), fan-out, budgets
│   ├── app/
│   │   ├── config.py               # RunConfig
│   │   ├── factory.py              # builds Services container from RunConfig
│   │   └── cli.py                  # `cadenzra compose spec.yaml`
│   └── common/
│       └── errors.py               # CadenzraError hierarchy
└── tests/
    ├── unit/                       # pure functions: assembly, analysis, validators,
    │                               #   interpretation transform, surface round-trips
    ├── integration/                # real LilyPond/FluidSynth, fake LLMs
    ├── fixtures/                   # golden LilyPond fragments, captured compiler
    │                               #   stderr, tiny MIDI files, canned LLM outputs,
    │                               #   golden score→performance MIDI pairs
    └── fakes/                      # in-memory protocol implementations
```

## Package responsibilities and the dependency direction

Dependencies point inward toward `model/`, which imports nothing from the rest of the package:

```
app → graph → {llm/services, verification, notation, performance, rendering} → interfaces → model
```

- **`model/`** is pure data — no I/O, no LLM, no subprocess. Anything two packages both need lives here. `model/primitives/` holds the foundational types ([03](03-musical-representations.md)): `Pitch` with its 12-EDO view, `MeterSpec`, absolute-offset time helpers, and the bar/beat↔offset conversion math (the math is a model concern; *when* to convert is an `llm` concern).
- **`interfaces/`** depends only on `model/`. If a protocol method needs a new type, the type goes in `model/`, keeping protocols vendor-free by construction.
- **`llm/`** is the only package that speaks both representational registers ([06](06-boundaries-llm-and-rendering.md)). Everything above and below it speaks internal only.
- **`notation/`, `performance/`, and `verification/`** are dominantly pure functions — the reason the system's core logic is testable without a single mock. Where a validator genuinely needs a service (a scaffolded compile, an LLM review), the service arrives as a protocol argument. `performance/` deliberately has no protocol wrapper — it is internal deterministic code, not a boundary.
- **`graph/nodes.py`** contains no logic worth testing — each node unpacks state, delegates, repacks. All intelligence lives below it; all wiring lives beside it in `build.py`. LangGraph could be replaced by editing `graph/` alone.
- **`app/factory.py`** is the single composition point. It is the only module that knows which concrete class implements which protocol.

## Conventions

- **Naming says what a unit does** — `assemble_section`, `parse_bar_check_warnings`, `dynamics_plan_to_cc_events`, `intervals_match_under_relation`. A function whose honest name needs an "and" gets split.
- **State is immutable in flight**: nodes return update dicts; `PipelineState` structures are never mutated in place. Frozen Pydantic models wherever the object is conceptually a value (everything in `model/` except `PipelineState` itself).
- **Errors**: one `CadenzraError` base; specific subclasses (`LLMOutputError`, `LilypondCompileError`, `SynthesisError`, `BudgetExhaustedError`) raised at boundaries; the CLI catches `CadenzraError`, prints the message and the path to partial artifacts, exits non-zero. Anything else escaping is a bug and crashes with a traceback, on purpose.
- **mypy strict** in CI; internal calls trust their types, and no code re-checks what the type system already guarantees.
- **Run outputs** land in `out/<spec>/` containing the five artifacts (LilyPond source, PDF, score MIDI, performance MIDI, audio) and the final `PipelineState` as JSON — a complete record for debugging generation quality after the fact.

  *Corrected in implementation.* This said `out/<run-id>/`, which would have given the artifacts a new home on every run and left no stable path to the current score. Artifacts overwrite in place; the **run log** is what accumulates, under `out/<spec>/runs/<timestamp>/`, because the question it answers — "why is this run worse than the last one?" — needs both runs present. It is three files, since three different questions get asked of a run: `llm.jsonl` (every LLM turn verbatim, failed attempts included, plus compiler invocations and validator rejections), `narrative.md` (the same flow readable, with the model's reasoning where the provider returns it), and `technical.log` (leveled tracing, `warning` by default, `info` to trace everything). Written by `common/runlog.py`; see also the note in [05](05-verification-and-feedback.md) on attempt history.
