# 08 — Engineering Principles

These are the working rules for the Cadenzra codebase. Each is stated as rule → why → how it applies *here*, with the domain-specific interpretations that keep the rules from being platitudes. Principles 1 and 2 are the two that shape the architecture itself; the rest govern the code that implements it.

## 1. Keep it simple; complexity is a stated choice

Default to the simplest correct solution; every departure is named out loud. This project has four big, deliberate complexity purchases, each justified in its own doc: **LangGraph** ([02](02-architecture-overview.md) — bought for the many conditional feedback loops), **the layered generation model** ([04](04-generation-layers.md) — bought because single-shot generation demonstrably fails on long-form music), **the protocol layer** ([06](06-boundaries-llm-and-rendering.md) — bought for testability against expensive, non-deterministic externals), and **the score/performance domain split** ([02](02-architecture-overview.md) — bought because the first piece's dynamics are inaudible without it, and because it converts a class of expensive regenerations into cheap parameter changes). Everything else defaults to simple: assemblers are string templates, validators are arithmetic, the interpretation transform is a pure function, the CLI is one command. When a change reaches for a fifth big purchase, it gets its own written justification first.

Scope discipline has a domain edge here: *musical* scope creep. Features like "also export MusicXML", "microtonal audio", "per-voice meters" are all plausible, all *deliberately un-foreclosed at the type level*, and all out of scope until a real piece demands them. Keeping a door open ([03](03-musical-representations.md)) is cheap; walking through it is a stated choice.

## 2. Exotic internals, musician surface

**Rule:** The system's internal representations may be as general and rigorous as the requirements demand. Every representation an LLM reads or writes — prompts, schemas, feedback messages, few-shot examples — speaks the ordinary language of musicians and textbook LilyPond. The translation between registers lives in `llm/prompts/` and `llm/parsers/` and nowhere else.

**Why:** The quality ceiling of the entire system is the LLM's compositional ability, and that ability rests on training-data density. Bar numbers, beats, note names, chord symbols, and vanilla LilyPond are the representations the model has seen millions of times; a bespoke coordinate system or house macro dialect would be the lowest-density representation in the system, sitting exactly where quality is decided. Internals face the opposite pressure — correctness and extensibility — so the two registers are allowed to differ, with a single owned seam between them.

**How it applies:**
- The LLM surface uses bar/beat; internals use absolute `Fraction` offsets. Parsers normalize inward, prompt builders render outward ([03](03-musical-representations.md), [06](06-boundaries-llm-and-rendering.md)).
- Fragments are a *disciplined subset* of textbook LilyPond — the good kind of constraint. No custom macros or house scaffolding ever appears in text an LLM reads or writes; conveniences live in the assembler.
- **Capability gating:** the surface shows only what the piece activates. Quarter-tones, additive-meter syntax, technique vocabularies stay invisible unless the spec summons them — an intuitive surface is also an unsurprising one, and mentioning a capability is an invitation to use it ([04](04-generation-layers.md)).
- Motifs travel as verbatim notation with a musician's instruction, never as ids. Feedback messages are authored like rehearsal notes, because their real consumer is a regeneration prompt ([05](05-verification-and-feedback.md)).
- The surface may be forgiving; the system is strict underneath. Parsers normalize, and deterministic validators re-derive everything decidable from the notation itself — so surface friendliness never costs correctness, because each guarantee is enforced once, at the layer that can actually check it.
- Surface design is an empirical variable: the live harness A/B-tests prompt surfaces against validator pass rates ([09](09-testing-and-milestones.md)). Where intuition about "intuitive" runs out, measurements decide.

## 3. Real stability, not theater

Every guard must name the real failure it prevents. The line runs straight through this codebase:

**Substance:** validating LLM outputs (they *will* be malformed), parsing compiler stderr defensively (it's an external text format), timeouts on subprocesses (they *do* hang), version-pinning LilyPond (its output formats drift), exact `Fraction` arithmetic for durations (floats *would* mis-sum 7/8 bars), tick tolerance in MIDI analysis (nested tuplets *do* round).

**Theater, rejected by name:** re-validating a `StructurePlan` that already passed its validator before using it downstream; range-checking pitches the type system guarantees; retrying a deterministic LilyPond compile; cross-checking the structured `techniques` list against notation markup (that's a LilyPond parser through the back door, guarding a cosmetic divergence); "sanity checks" on frozen models between nodes. State that passed a validator is *trusted* until the layer that owns it regenerates it — that trust is the whole point of validating once, properly, at the right layer.

## 4. Fail loud; no fallbacks for impossible states

The catastrophic quiet failure in this domain is a **plausible-looking but wrong score** — a bar silently padded to fit the meter, a range violation "fixed" by octave transposition, a declared fugue entry that isn't the subject, a missing section skipped. Every one of these is worse than a crash, because the human downstream (a choir!) trusts the artifact.

Inside our code: direct lookups, trusted types, no `except Exception`. If the assembler finds a `(section, voice)` key missing from `state.voices` after validation supposedly passed, that is a broken invariant — crash with a traceback; a test should have tripped it.

At boundaries: bounded retries for LLM transport/output failures; specific exceptions with full evidence for subprocess failures; and when a retry budget exhausts, `BudgetExhaustedError` — surfaced to the user with partial artifacts and the accumulated feedback, exit non-zero. The pipeline **never** completes a run by degrading the music. There is no "best effort" score.

## 5. External systems sit behind Protocols

All five external touchpoints — generator LLM, audio critic, feedback router, LilyPond, FluidSynth — are Protocols in `interfaces/`, implemented in their domain packages, wired only in `app/factory.py` ([06](06-boundaries-llm-and-rendering.md), [07](07-project-structure.md)). Protocols speak music (`generate_voice`, `critique`), not transport. Vendor SDKs import only inside `llm/clients/`; `subprocess` imports only inside `rendering/`. Needing to inspect a concrete type above the boundary means the protocol is wrong — extend it.

The rule cuts both ways: `interpret_performance` is deliberately *not* behind a protocol, because it is deterministic internal code with no vendor and no non-determinism — a protocol there would be ceremony. Protocols mark genuine externality, not "things that feel important."

This is one of the "established pattern" cases where the abstraction *is* the simple version: the day-one payoff is that every pipeline test runs against fakes with zero patching, and the audio critic can be swapped per-run by config.

## 6. Structured LLM outputs, parsed in one place

Every LLM result is a forced tool call, validated in `llm/parsers/`, failing as `LLMOutputError` — never regex-scraped, never defaulted ([06](06-boundaries-llm-and-rendering.md)). Business code never sees raw model text. New capability = prompt builder + schema + parser + protocol method, always all four.

The domain nuance: LilyPond fragments are structured in *shape* (tool call) but validated in *substance* by the compiler and MIDI analysis. Don't duplicate the compiler's job in a parser; don't let a fragment skip the compiler because its JSON envelope validated.

## 7. One purpose per unit, named for exactly what it does

The pipeline's node taxonomy is this rule at architecture scale: generators generate, validators validate, assemblers assemble, the interpreter interprets — and a node doing two of those is two nodes. So is the domain split: score truth and performance interpretation are different purposes with different owners. At function scale: side effects live at the edges (adapters, node wrappers); `notation/`, `performance/`, and `verification/` stay dominantly pure, which is why the entire musical core is testable with values in, values out. `assemble_and_validate_section` is a name that fails code review.

## 8. Right-sized abstraction

Abstract on demonstrated need; the heuristic is *how expensive is it to abstract later?* Applied decisions, recorded so they aren't relitigated silently:

- **Abstracted/generalized now** despite being early: the protocol boundary (established pattern; retrofitting after vendor imports metastasize is expensive); `FeedbackItem` as the universal failure currency (every loop depends on its shape); **absolute-`Fraction` time, generalized `Pitch`, and additive `MeterSpec`** ([03](03-musical-representations.md) — each is nearly free today and re-keying the system later would touch everything); the **interpretation seam** (v1 implements dynamics curves + identity; re-plumbing the render path later would touch artifacts, router, and critic at once); `MotifLibrary` (the docs promise "themes that return"; without material as state that promise is unverifiable).
- **Deliberately not abstracted:** a "validator framework" (validators sharing a call signature is enough structure); a general "music IR" between the models and LilyPond (the models *are* the IR — and principle 2 independently kills a note-list JSON layer, which would be the lowest-training-density representation in the system); per-voice meters (the *coordinate system* that enables them is bought; the feature is not); a protocol around the interpretation transform.
- **Watch items:** a second notation backend (MusicXML export, Strudel) triggers a target interface for `notation/assemble.py` *then* — cheap precisely because assembly is pure. Sub-section dynamic shaping divergence between printed hairpins and plan-driven CC curves ([03](03-musical-representations.md)) is accepted for v1; if the critic keeps flagging it, dynamics annotations become structured per-voice data — a known door, not built.

## 9. Fix bugs test-first; pin the contract

A Cadenzra bug is usually a violated musical contract — "validator accepted a bar that overfills 7/8", "assembler dropped a tempo change at a section boundary", "a tonal answer passed verification while deviating in contour". The discipline: write the failing test first, assert the *contract* ("no bar may exceed its meter" — parameterized over meters, including additive ones), not the instance ("this fragment in this key"), fix minimally, run the surrounding suite. Golden-fixture tests ([09](09-testing-and-milestones.md)) make this cheap: most contract tests are "this crafted-bad artifact must be rejected with a FeedbackItem naming bar N."

When the bug was a broken internal invariant (the assembler consumed unvalidated state; a track lost its channel), the durable fix is making the invariant fail loudly at its source, with the test proving it does.

## 10. One task at a time, verified before the next

The build order in [09](09-testing-and-milestones.md) is this rule applied to the whole project: each milestone is a *runnable, verified* slice, and no milestone starts before the previous one demonstrably works, because a failure inside an unverified six-layer pipeline is a debugging pile. Empirical unknowns are scheduled as verification steps, not assumptions — whether LilyPond emits quarter-tone pitch bends is *checked* in M0, not believed. LLM-dependent steps that can't be meaningfully verified offline are marked as such and verified with a budgeted live run — never quietly assumed to work because the fakes passed.
