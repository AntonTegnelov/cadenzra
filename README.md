# Cadenzra — Design & Architecture Documentation

*Cadenzra* is the working name for the AI music composition pipeline: a system that generates complete musical works as **correct, publication-quality sheet music first**, with audio rendered from that same source through a distinct performance-interpretation stage, orchestrated as a layered generate-verify loop in LangGraph.

## Reading order

| Doc | Contents |
|---|---|
| [01 — Vision & Scope](01-vision-and-scope.md) | What the system is, hard requirements, non-goals, success criteria |
| [02 — Architecture Overview](02-architecture-overview.md) | The layered pipeline, LangGraph graph shape, state model, node taxonomy |
| [03 — Musical Representations](03-musical-representations.md) | Every data format in the pipeline; the internal/surface representation split; why LilyPond is canonical |
| [04 — Generation Layers](04-generation-layers.md) | The generator nodes: structure planner, motif library, harmonic skeleton, voice elaboration; prompt strategy |
| [05 — Verification & Feedback](05-verification-and-feedback.md) | Validator taxonomy, the `FeedbackItem` contract, routing, retry budgets |
| [06 — Boundaries: LLMs & Renderers](06-boundaries-llm-and-rendering.md) | Protocol definitions for every external system; structured-output discipline; the musician-surface translation layer |
| [07 — Project Structure](07-project-structure.md) | Repository layout, package responsibilities, dependency wiring |
| [08 — Engineering Principles](08-engineering-principles.md) | The coding rules for this codebase, with domain-specific applications |
| [09 — Testing & Build Milestones](09-testing-and-milestones.md) | Testing strategy per component class; the incremental order in which to build the system |

## The system in one paragraph

A user describes a piece (genre, instrumentation, meters, mood, length). A **structure planner** produces a formal plan; where the plan calls for recurring material (a fugue subject, a riff), a **motif library** is generated; a **harmonic skeleton generator** produces chord progressions per section; **voice generators** elaborate each part as LilyPond fragments against that skeleton. Deterministic and LLM-based **validators** check every artifact at the level it was produced — single voice, assembled section, full score — and failures loop back as structured feedback to exactly the node that can fix them. The validated LilyPond score compiles to PDF (the sheet music) and a canonical *score MIDI*; a deterministic **performance interpretation** stage transforms score MIDI into *performance MIDI* (continuous dynamics, swing, micro-timing), which FluidSynth renders to audio for a multimodal critic's final quality gate. The outputs — score, score MIDI, performance MIDI, audio, LilyPond source — are all consistent because they derive from one canonical text representation.

## The two design commitments everything else follows from

**Notation is the source of truth.** Audio is compiled from the score, never the reverse; no artifact is ever edited downstream of its source.

**Exotic internals, musician surface.** The system's internal representations may be as general as the requirements demand (exact fractional time, tuning-agnostic pitch, additive meters); every prompt, schema, and feedback message an LLM sees speaks the ordinary language of musicians and textbook LilyPond, because that is where the model's training-data density — and therefore its compositional ability — lives. See [08](08-engineering-principles.md), principle 2.
