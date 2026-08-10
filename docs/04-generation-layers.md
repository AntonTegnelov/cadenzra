# 04 — Generation Layers

This doc specifies each generator node: its inputs, output contract, prompt strategy, and the specific LLM failure it is designed around. All generators call the LLM through the `GeneratorLLM` protocol with forced tool calling for structured layers, and through a validated-text path for LilyPond fragments ([06](06-boundaries-llm-and-rendering.md)).

## The surface rules all generators share

Two rules from principle 2 ([08](08-engineering-principles.md)) govern every prompt in this doc:

**Speak musician.** Prompts and schemas use bar numbers, decimal beats, note names, chord symbols, meter strings like "7/8 (2+2+3)", Italian dynamics, and plain music-theory prose. Internal representations (absolute `Fraction` offsets, generalized pitch) never appear at the surface; `llm/prompts/` and `llm/parsers/` translate ([03](03-musical-representations.md)).

**Capability gating: the surface shows only what the piece needs.** Microtonal accidentals, additive-meter syntax, technique vocabularies, nested-tuplet guidance — none of it appears in a prompt unless the `PieceSpec`/`StylePack` activates it. This is behavioral, not just economical: mentioning quarter-tones in every prompt is an invitation to use them, and an intuitive surface is also an *unsurprising* one. Prompt builders assemble the instruction set per-run from what the spec activates; the exotic machinery exists in the system, invisible until summoned. The fragment-contract rules themselves stay short and mechanical in the prompt — the enforcement loop carries the real weight, so the prompt needn't be a legal document.

## `derive_style_pack`

**In:** `PieceSpec.style_prompt`, `voices`, `meters_allowed`. **Out:** `StylePack`.

One LLM call that converts free-text style intent into the concrete, checkable material every other node consumes: prose idioms, vetted one-bar rhythmic cells per allowed meter (requested *with groupings spelled out*: "7/8 as 2+2+3: `c8 c c c c c4`"), harmony guidance, validator policies as enum choices, interpretation defaults (does this style swing? sit behind the beat?), and short in-style LilyPond fragments for downstream few-shot use. Generated cells are compile-checked (one-bar scaffold with a bar check) before the pack is accepted — a bad cell would poison every downstream voice generation.

This node exists so that style interpretation happens exactly once. Without it, "Tool-inspired" would be independently re-interpreted by the planner, the harmony generator, and every voice generation — with drift between them guaranteed.

## `plan_structure`

**In:** `PieceSpec`, `StylePack`. **Out:** `StructurePlan`.

High-level formal planning is the layer LLMs are naturally best at — compact, abstract, closer to prose than to notation. The prompt supplies the target duration, meter palette, voices (and groups, if any), and the style pack's dynamics-arc guidance, and requests a section list with an explicit form summary, structured per-section dynamics arcs, and — where the form involves recurring material — `materials_needed` briefs plus declared `MaterialEntry` placements.

Form-specific knowledge arrives as *data*: for a fugue, the style pack and spec drive the planner to declare a subject brief and exposition entries with relations ("tonal answer at the fifth"); for concerto grosso, `active_voices` alternates group references. No form has a code path.

Bar counts per section are derived arithmetic (`target_minutes`, tempo, meter), and the structure validator re-checks the sum against the target duration with tolerance — the LLM proposes, arithmetic disposes.

## `generate_motifs`

**In:** `StructurePlan.materials_needed`, `StylePack`, `PieceSpec` ranges for the voices that will carry each motif. **Out:** `MotifLibrary`. Skipped entirely when the plan declares no materials.

Each brief becomes one motif: a short LilyPond fragment (typically 1–4 bars) under the same fragment contract as voices, generated with the style pack's cells and few-shots as context. Motifs are the highest-leverage notes in the piece — every declared entry across the whole work derives from them — so `validate_motifs` gives them both the deterministic treatment (scaffolded compile, range-fit for every voice that will carry them under every declared relation) and an LLM review for memorability/style. Range-fit under relations matters: a subject that fits the soprano may leave the alto's "fifth below" answer under its floor; catching that here costs one check, catching it later costs regenerated sections.

## `generate_harmony`

**In:** one `SectionPlan`, `StylePack`, relevant motifs *as notation*, plus the last two harmonic events of the previous section. **Out:** `HarmonicSkeleton` for that section.

Called once per section, sequentially in performance order — sequential (unlike voice generation) because harmonic continuity across boundaries is the point; the previous tail is the sliding-window context. Where the plan declares motif entries in a section, the motif notation is included so the harmony *accommodates* the material (a fugue subject implies its harmonization; a riff implies its pedal) rather than fighting it.

The surface schema is bar/beat/chord-symbol events ([03](03-musical-representations.md)); durations must sum exactly to the section length — stated in the prompt *and* enforced by the validator, because stating it roughly halves the failure rate and enforcing it catches the rest.

## `generate_voice`

**In:** one (section, voice) pair — its `SectionPlan`, `HarmonicSkeleton` (rendered as a bar/beat chord chart), `VoiceSpec`, `StylePack`, any `MaterialEntry` for this voice *with the motif verbatim in LilyPond* plus a musician's instruction ("enter with this subject at bar 5, real answer at the fifth"), the final 2–4 bars of the same voice in the previous section (sliding window), and, when regenerating, the failing fragment plus its `FeedbackItem`s. **Out:** a `VoicePart`.

This is the workhorse node and the one engineered most heavily around LLM weakness:

**Small blast radius.** One voice × one section is typically 8–24 bars of a single line — comfortably inside the window where LLM notation stays accurate. The layered design exists largely so that *this* call can be this small.

**Cell-anchored rhythm.** The prompt instructs the generator to build rhythm by selecting, repeating, and varying `StylePack.rhythmic_cells` for the section's meter, shown with their groupings. Free rhythmic invention in 7/8 is where beat-count errors concentrate; varying a correct cell rarely breaks the bar.

**The fragment contract as explicit instructions.** Absolute pitch, explicit durations, `|` at every barline, no structural commands, techniques declared both as markup and structurally ([03](03-musical-representations.md)). Prompted *and* machine-enforced; the prompt exists to make the enforcement loop converge fast, not as the actual guarantee.

**Texture comes from the plan.** For `texture: "unison"` sections, one rhythmic surface is generated first and other voices are constrained to it; for imitative textures, entries come from declared materials and episodes are prompted with the material verbatim. The plan's texture field selects among prompt strategies inside the node — deliberately a prompt-level branch, not separate node types, until a real need splits them.

**Fan-out.** Within a section, voices generate concurrently (independent given the skeleton), except where texture creates ordering dependencies as above. Across sections, generation is sequential per voice so the sliding window is available.

  *Corrected in implementation (2026-08-10).* Concurrency is now conditional on texture: contrapuntal sections (imitative, fugal, canon, polyphonic — matched on the plan's texture text) generate **sequentially in entry order, each voice shown the finished lines before it**. Independence given the skeleton coordinates pitch class but not motion, and the double-fugue's first pass measured ~44 distinct parallel passages between blind voices — a base rate no prompt could lower (`docs/harness-results/cost-deep-dive.md`, Part 1). Homophonic textures keep the concurrent fan-out.

**Words are not written here.** A sung part is told only that it will be sung, and to leave room for a syllable per note. The words themselves come from the two layers below, after the music exists.

## `plan_lyrics`

**In:** spec, style pack, structure plan. **Out:** a `LyricPlan` — one story for the piece, and per sung section a story beat, a voice relationship, an optional rhyme scheme, optional devices from a controlled vocabulary, and an optional refrain link.

Runs immediately after `plan_structure` and is **skipped entirely** for instrumental pieces, so a fugue or a synthwave track never sees a word of the lyric vocabulary — the same conditional skip the motif layer uses, for the same capability-gating reason.

**Why a layer and not a field on the plan.** Conditionally mutating the structure schema per spec is messier than a gated layer, the plan prompt is already large, and directives need their own convergence loop. Full reasoning in [10](10-lyrics.md).

## `generate_lyrics`

**In:** a `LyricsContext` — the section's directive, its *realized notation* verbatim, the language, the story, the preceding sections' words, and a refrain source when one is declared. **Out:** a `SectionLyrics` covering every singing voice in the section.

**One call per section, all voices at once.** This is the layer's whole reason for existing. Voices generated separately invent separate texts — one run produced a piece with one voice in Latin and another in English simultaneously — and no amount of prompting fixes a context that structurally cannot see the other singer. One writer, one text.

**It deliberately breaks the fan-out symmetry above**, under the same clause that already allows it: texture creates ordering dependencies. Coordinated words are that case, taken to its conclusion.

**Words follow notes.** The music is finished and shown verbatim; the words are fitted to it. When cross-voice checks later rewrite a voice's music, that section's words are regenerated after it — notation is the source of truth and everything downstream of it rebuilds ([03](03-musical-representations.md)).

## Regeneration prompts

When a validator bounces a fragment back, the regeneration prompt contains: the original task context, the rejected fragment, and the structured feedback rendered **like a rehearsal note** — concrete, mechanical, in musician's terms: "bar 7 contains 9 eighth-notes; the meter is 7/8 (2+2+3) — remove one eighth or retie", "d''4 in bar 3 exceeds the alto ceiling of c''", "the entry at bar 5 should be the subject a fifth up; beats 3–4 deviate from its interval sequence". Feedback precision is a validator design requirement, not a nicety — the regeneration prompt is `FeedbackItem.message`'s real consumer ([05](05-verification-and-feedback.md)). The failing fragment is included because minimal repair preserves accepted material; regeneration from scratch is the fallback when repair fails twice. *Implemented as written (2026-08-10):* bar-scoped feedback repairs by patch — `rewrite_bars` offers only the flagged, unprescribed bars, spliced deterministically (`notation/scaffold.split_bars`) — and two failed patches fall back to full regeneration (`app/compose.py`, `_PATCH_ATTEMPTS`). One refinement the first live runs forced (2026-08-10): LilyPond reports only the first failed bar check per compile, so multiple bad bars surface one at a time; a patch that clears every bar it was offered and reveals only never-offered bars consumes no retry budget — the reveal is the compile's discovery, not the patch's failure, and is bounded by the bars on the page.

## What generators never do

Generators never see raw validator internals, never see internal coordinates, never receive another voice's full notation except through defined texture/material strategies, and never emit structural LilyPond. Anything a generator writes is either validated JSON (structured layers) or a fragment that must survive compilation and analysis before it becomes part of the piece.
