# 05 — Verification & Feedback

Verification is the half of the system that makes the other half trustworthy. The design principle throughout: **prefer decidable checks over judgment, prefer existing tools over new parsers, and make every failure a structured, routable object.**

## Validator taxonomy

Three classes, in decreasing order of trust and increasing order of cost:

**Deterministic validators** — pure Python over parsed data. No LLM, no ambiguity, no flakiness. These carry the correctness guarantees from [01](01-vision-and-scope.md): bar arithmetic, ranges, gaplessness, structural sums, motif-entry relationships. A deterministic validator's verdict is final.

**LLM validators** — an LLM asked a *narrow* question with a structured verdict schema ("does this section plan realize the requested arc? verdict + reasons"). Used only for properties that are genuinely not decidable (formal coherence, stylistic fit, memorability of a subject). Their verdicts route feedback but are advisory in tone — they can send work back within budget, never veto a piece that passes all deterministic checks on the final attempt.

**The audio critic** — one multimodal LLM node listening to the rendered audio ([06](06-boundaries-llm-and-rendering.md)). Holistic by design: it catches "the middle is mud" and "the meter doesn't groove", not "parallel fifth in bar 37" — precise diagnostics are the deterministic validators' job, and asking audio models for them produces confident nonsense.

## The analysis path: compile, then inspect score MIDI

The pivotal implementation decision: **Cadenzra never parses LilyPond notation itself.** Pitch-and-timing analysis works on the *score MIDI* that LilyPond compiles, via `mido`, with one voice per track/channel (the assembler's hard invariant, [03](03-musical-representations.md)). Meter correctness comes from the compiler's own bar checks. Syntax correctness comes from the compiler's exit status.

Two rules refine this:

**Validators analyze the score domain only.** All musical verification runs on score MIDI — the quantized truth of what the notation says. Performance MIDI (swing, offsets, curves) is downstream interpretation and is *never* analyzed by validators; it is judged only by the critic's ears. Verifying the composition on interpreted timing would turn every deliberate groove into a false rhythm error.

**Analysis compares with tick tolerance.** MIDI quantizes; deeply nested tuplets round at tick resolution. Onset and duration comparisons carry a small fixed tolerance so that correct-but-rounded rhythms don't false-positive. (Consequence of the same fact: enharmonic spelling is invisible in MIDI — spelling errors are cosmetic and out of validator scope; wrong notes are not. A notation-level linter could be added later behind the same validator interface if engraving quality demands it.)

Per-fragment validation compiles each fragment inside a minimal scaffold (the section's meter, a single staff) — catching errors while the blast radius is one voice, before assembly.

## Validator inventory

**`validate_structure`** *(deterministic + LLM)* — sections nonempty and uniquely named; every meter in `meters_allowed`; bar-count sum within tolerance of `target_minutes`; every active voice/group resolves against the spec; every `MaterialEntry` references a declared material brief, lands inside its section, and addresses a participating voice; dynamics plans well-formed. LLM check: form summary vs. requested arc.

**`validate_motifs`** *(deterministic + LLM)* — per motif: scaffolded compile clean; fragment contract respected; **range-fit under every declared relation** — the motif transposed per each `MaterialEntry.relation` must fit inside the carrying voice's range (cents comparison on `Pitch`), because a subject that fits the soprano can put the alto's fifth-below answer under its floor. LLM check: distinctiveness and style fit — these notes recur through the whole piece and deserve the review.

**`validate_harmony`** *(deterministic + LLM)* — events ordered, gapless, exactly filling the section (exact `Fraction` arithmetic on internal offsets); chord symbols parseable. LLM check: progression fits `harmony_guidance`, boundary continuity, accommodation of declared material.

**`validate_lyric_plan`** *(deterministic)* — every sung section has a brief and no unsung one does; devices are in the controlled vocabulary; a declared refrain points at a section that already happened; anything the spec demanded (a scheme, particular devices) is actually placed somewhere. Cheap checks on a cheap artifact, before a single word is written ([10](10-lyrics.md)).

**`validate_section_lyrics`** *(deterministic + LLM)* — per sung section: each voice's words compiled against its own music, so the compiler decides syllable alignment as it always has; a `unison` relationship means identical text across voices; a declared refrain reproduces its source; a declared rhyme scheme holds, checked phonetically through CMUdict and English-only, with unknown words skipped rather than failed. LLM check: the devices the directive asked for, verified **blind** — a reader is shown the words and the whole vocabulary, never the request, and the comparison happens outside the model. Advisory, one nudge, never a veto ([10](10-lyrics.md)).

**`validate_voice`** *(deterministic)* — per fragment: scaffolded compile succeeds with zero bar-check warnings; every note within `[range_low, range_high]` (from the fragment's MIDI, in cents); explicit-duration and no-structural-commands contract respected (a token-level denylist scan — the one place a regex touches LilyPond, justified because a denylist is not a parser); `TechniqueSpan`s use the controlled vocabulary and land inside the fragment; lyric syllable count matches note count where applicable (compiler warning).

**`validate_section`** *(deterministic)* — all voices assembled: cross-voice checks on the section's score MIDI. Parallel fifths/octaves between voice pairs, judged against `StylePack.parallel_fifths_policy`; voice crossings against the plan's texture; **harmonic alignment** — at each harmonic event onset, sounding pitches (12-EDO view) are checked against the chord's pitch-class set, with non-chord tones permitted per `dissonance_policy` (passing/neighbor tones resolved by step always allowed; the checker flags *sustained* unexplained clashes); **material-entry verification** — for each declared `MaterialEntry`, the interval sequence and rhythm profile at the declared position must realize the motif under the declared relation. Exact transpositions ("P5 up", "octave down", "inversion") check as strict interval-sequence equality after the transform; elastic relations ("tonal answer") check with a bounded per-interval deviation (the idiom adjusts scale degrees, not the contour). Failures name the offending voice(s) and the first deviating beat, so the router can target regeneration.

**`validate_score`** *(deterministic + LLM)* — full compile: zero errors, zero bar-check warnings, PDF and score MIDI produced; all sections present in order; tempo/meter/key changes at exactly the planned boundaries (from MIDI meta events); channel/track invariant intact. LLM check: read the plan + a piano-reduction summary of the realized music and judge arc coherence and boundary smoothness.

**`critique_audio`** *(critic)* — the rendered audio (a *performance*) goes to the audio critic with pointed questions: overall quality, muddiness/register clashes, rhythmic feel in the odd meters, balance, style match. Output is a structured verdict with localized observations ("section B, lower voices, sounds cluttered") the router can act on.

**Corrected by measurement: the critic is not told the intent.** This doc originally sent "the intent summary" along with the audio, and asked the critic whether the dynamics arc lands. Both are now known to be mistakes. Played a performance rendered at one constant velocity with no expression at all, a critic briefed on the intended arc reported hearing it "realized with clarity and emotional weight"; given the identical audio and a brief stripped of intentions, the same critic said nothing about dynamics and described only the meter and counterpoint. An LLM judge handed the answer key grades against the key rather than the work. `CritiqueBrief` therefore carries only what an observation needs to be *localized* — section labels, meters, voice names — and "did the arc land?" moved to `verification/audio.py`, which decides it by comparing the planned controller range against the one the performance MIDI actually carries. That is this doc's own first principle applied to a question it had misfiled: prefer decidable checks over judgment. Recorded in full in `docs/harness-results/`.

## `FeedbackItem` — the routing contract

Every validator failure and critic observation is one shape:

```python
class FeedbackItem(BaseModel):
    source: str                            # emitting node
    level: Literal["structure", "motif", "harmony", "lyric", "voice",
                   "section", "score", "interpretation", "render"]
    section_id: SectionId | None
    voice_id: VoiceId | None
    location: Fraction | None              # internal: offset within section
    message: str                           # authored like a rehearsal note —
    evidence: str | None                   #   bar/beat terms, concrete, mechanical
```

`level` + the ids determine the routing target outright for validator feedback. Internally the location is an offset; the `message` always speaks bar/beat, because its real consumer is a regeneration prompt ([04](04-generation-layers.md)) — feedback is part of the LLM surface and follows the surface rules.

## `route_feedback` — interpreting the critic

Validator feedback routes by table lookup — no intelligence needed. The router node's real job is the **audio critic's qualitative feedback**: "section B sounds cluttered" could be a texture problem (→ `generate_voice` for B's inner voices), a harmonic-density problem (→ `generate_harmony` for B), an interpretation problem (→ adjust `InterpretationParams`: curve intensity, offsets), or a rendering problem (→ `render_audio` with different balance/SoundFont). The router is one narrow LLM call mapping each observation to a `FeedbackItem` with a concrete `level`/target, given the plan as context. Anything it cannot localize routes to the *cheapest* plausible target first — **interpretation and rendering before harmony before structure** — because misrouting a vague complaint to `plan_structure` would cascade a full regeneration on the weakest evidence in the system, while an interpretation-parameter change costs one deterministic re-render. The score/performance split earns much of its keep right here: "sounds stiff" is now a knob, not a rewrite.

## Budgets and failure

Retry budgets and the fail-loudly-with-partials contract are defined in [02](02-architecture-overview.md); validators themselves are stateless and know nothing about attempts. Two rules keep the loops honest:

1. A validator re-runs *in full* after every regeneration — there is no "fixed the reported issue, skip the rest" path, because regeneration can introduce new errors anywhere in the fragment. This holds for bar-scoped patch repairs too (2026-08-10): a spliced part re-runs `validate_voice` whole — the patch narrows what the model may *change*, never what gets *checked*.
2. Feedback items from superseded attempts are cleared when their target regenerates; only current, unresolved feedback lives in state. History goes to the run log, not the working state.

The run log this rule depends on now exists (`common/runlog.py`, under `out/<spec>/runs/<timestamp>/`). Every rejection is recorded there with its loop key, attempt number and validator messages, alongside the prompt that produced the rejected artifact and the model's reasoning about it — so the history state drops is reconstructable, which is the premise that made dropping it safe. See [07](07-project-structure.md) for the file layout.
