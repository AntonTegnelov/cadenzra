# 02 — Architecture Overview

## The core idea: layered generation, scoped verification

A single LLM call cannot hold a whole multi-voice, multi-section piece coherently. Cadenzra therefore generates top-down through **abstraction layers**, each producing a compact artifact that constrains the next:

```
PieceSpec (user intent)
   │
   ▼
StylePack ──────── concrete idioms, constraints, rhythmic cells derived from the spec
   │
   ▼
StructurePlan ──── formal map: sections, meters, keys, bar counts, texture,
   │                dynamics arcs, and declared material entries
   ▼
MotifLibrary ───── named reusable material (subjects, riffs, themes) —
   │                only when the plan declares any
   ▼
HarmonicSkeleton ─ chord progression + harmonic rhythm, per section
   │
   ▼
VoiceParts ─────── LilyPond fragments, per section × per voice
   │
   ▼
Assembled score ── one canonical LilyPond file
   │
   ▼
Score artifacts ── PDF · score MIDI (quantized, canonical)
   │
   ▼
Performance ────── performance MIDI (interpreted) · audio
```

Each layer is verified **at the level it was produced**, and failures route back to the *smallest* unit that can fix them. A wrong beat count in the alto's bars 9–12 regenerates four bars of one voice — not the section, not the piece. This scoping is the system's main defense against both cost explosion and the LLM "drift" problem: every regeneration happens in a small, well-constrained context.

## The score/performance split

The pipeline distinguishes two domains with different natures:

**The score domain** ends at *score MIDI* — LilyPond's quantized, mechanical compilation of the notation. It is canonical: validators analyze it, motif relationships are verified against it, and it is what the notation *says*.

**The performance domain** begins at `interpret_performance`: a deterministic transform (score MIDI + `InterpretationParams` → performance MIDI) that owns everything a performer adds and a score omits — continuous dynamics curves (CC11/CC7) realizing the plan's dynamics arcs on held notes, swing ratios, per-voice micro-timing offsets, pitch-bend synthesis for glissandi/portamento, and technique→timbre mappings. FluidSynth renders performance MIDI; the audio critic hears the *performance*.

This split exists because score information and performance information have different sources of truth (the notation vs. the interpretation parameters), different validators (arithmetic vs. ears), and different fix paths ("wrong notes" regenerates music; "sounds stiff" adjusts parameters — vastly cheaper). It also preserves the no-downstream-editing principle: performance MIDI is a *derived* artifact with a single owning transform, exactly like the PDF. In v1 the transform implements dynamics curves (the choir piece needs them) and identity for the rest; the seam is the point.

## The graph

The pipeline is a LangGraph `StateGraph`. Node taxonomy:

| Kind | Nodes | Nature |
|---|---|---|
| **Generators** | `derive_style_pack`, `plan_structure`, `generate_motifs`, `generate_harmony`, `generate_voice` | LLM calls with structured output |
| **Assemblers** | `assemble_section`, `assemble_score` | Pure functions — deterministic template filling |
| **Validators** | `validate_structure`, `validate_motifs`, `validate_harmony`, `validate_voice`, `validate_section`, `validate_score` | Mostly pure Python; some LLM-assisted ([05](05-verification-and-feedback.md)) |
| **Renderers & interpreter** | `render_score` (LilyPond → PDF + score MIDI), `interpret_performance` (pure transform), `render_audio` (FluidSynth) | Two subprocess boundaries around one pure stage |
| **Critic** | `critique_audio` | Multimodal LLM listening to the rendered audio |
| **Router** | `route_feedback` | Maps validator/critic feedback to the target node |

Edges follow the layer order; every validator has a conditional edge that either advances or loops back with feedback attached to state. `generate_motifs` runs only when the plan declares material entries; otherwise the edge skips it. `generate_voice` fans out per (section, voice) pair — independent given the skeleton, so concurrent.

```
derive_style_pack
      ↓
plan_structure → validate_structure ⇄ (fail: plan_structure)
      ↓ pass
generate_motifs → validate_motifs ⇄ (fail: generate_motifs)     [skipped if no materials]
      ↓ pass
generate_harmony → validate_harmony ⇄ (fail: generate_harmony)
      ↓ pass
generate_voice [× section × voice, parallel] → validate_voice ⇄ (fail: generate_voice)
      ↓ pass
assemble_section → validate_section ⇄ (fail: generate_voice[targeted])
      ↓ pass
assemble_score → validate_score ⇄ (fail: assemble_section / generate_voice[targeted])
      ↓ pass
render_score → interpret_performance → render_audio → critique_audio
      ↓ fail                                              ↓ pass
route_feedback → {plan_structure | generate_harmony |     outputs
                  generate_voice | interpret_performance |
                  render_audio}
```

## State

Graph state is a single Pydantic model, append-mostly, holding the artifacts of every layer plus feedback:

```python
class PipelineState(BaseModel):
    spec: PieceSpec
    style: StylePack | None = None
    structure: StructurePlan | None = None
    motifs: MotifLibrary | None = None
    harmony: dict[SectionId, HarmonicSkeleton] = {}
    voices: dict[tuple[SectionId, VoiceId], VoicePart] = {}
    sections: dict[SectionId, AssembledSection] = {}
    score: AssembledScore | None = None
    interpretation: InterpretationParams | None = None   # defaults from StylePack;
    artifacts: RenderedArtifacts | None = None           #   tunable by the router loop
    feedback: list[FeedbackItem] = []                    # open issues, consumed by router
    attempts: dict[str, int] = {}                        # retry bookkeeping per loop key
```

All the models are defined in [03](03-musical-representations.md); `FeedbackItem` in [05](05-verification-and-feedback.md). `InterpretationParams` lives in state (not buried in the interpreter) precisely so the critique loop can adjust it — "sounds rushed" becomes a parameter change, not a regeneration. Nodes are **pure with respect to state**: each takes `PipelineState`, returns the fields it changed, and never mutates shared structures in place. Side effects (LLM calls, subprocesses, file writes) live only in the injected services the node calls through protocols ([06](06-boundaries-llm-and-rendering.md)).

## Feedback loops and termination

Every generate⇄validate loop has a **bounded retry budget** (default 3, configurable per loop). The `attempts` map is keyed by loop identity — e.g. `voice:{section}:{voice}` — so one stubborn alto line cannot starve the rest of the piece. When a budget is exhausted the pipeline **fails loudly**: it raises a specific error, writes all artifacts produced so far (including the failing fragment and its accumulated feedback) to the output directory, and exits non-zero with a message naming exactly which unit failed and why. It never pads, truncates, or auto-"fixes" music to force completion — a silently corrupted score is the one output this system exists to prevent.

The audio-critique loop gets a stricter budget (default 1 re-route into the score domain, plus a small independent budget for interpretation-parameter adjustments, which are cheap) because it is the most expensive and least precise loop; its purpose is catching gross problems, not converging on taste.

## Why the compiler is a load-bearing component

LilyPond is not only the output format — it is the pipeline's most trustworthy validator. Design decisions in [03](03-musical-representations.md) and [05](05-verification-and-feedback.md) deliberately arrange for the compiler to do verification work (bar checks, syntax, score-MIDI derivation for analysis) instead of hand-writing a LilyPond parser. The system leans on two mature externalities — the LilyPond compiler and Pydantic validation of tool-call JSON — and keeps its own verification code small and decidable.

## Where LangGraph earns its complexity

LangGraph is a real dependency with a learning curve, so per [08 — keep it simple](08-engineering-principles.md) the choice is stated explicitly: the design contains at minimum eight conditional feedback edges, a conditional skip, a fan-out/fan-in over (section × voice), per-loop retry accounting, and a content-based router. Hand-rolling that as nested `while` loops is more code and less inspectable. The mitigation for framework lock-in is that **nodes are plain functions over `PipelineState`** and all wiring lives in one module (`graph/build.py`) — the framework touches the shape of the program, not its substance.
