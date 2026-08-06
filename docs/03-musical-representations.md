# 03 — Musical Representations

Every artifact that flows between nodes has a defined, validated shape. This doc defines them — and, first, the representational rule that governs all of them.

## The internal/surface split

Cadenzra maintains two representational registers with an explicit translation layer between them:

**Internal representations** are engineered for correctness and generality: exact `Fraction` time, tuning-agnostic pitch, additive meters. They exist so that hard requirements (odd meters, motif verification) and identified extension points (microtonality, polymeter) don't require re-keying the system later.

**Surface representations** are what LLMs read and write, engineered for training-data density: bar numbers, decimal beats, standard note names, chord symbols, textbook LilyPond, musician's prose. An LLM never sees "offset 17/8 whole notes from section start"; it sees "bar 5, beat 2.5".

The translation lives in exactly one place — `llm/prompts/` renders internal state into the musician's view; `llm/parsers/` normalizes the musician's view back ([06](06-boundaries-llm-and-rendering.md)). The surface is allowed to be forgiving (a musician's "beat 2.5" is mildly ambiguous under some additive groupings) because parsers normalize and deterministic validators re-derive everything decidable from the notation itself: familiar on the wire, strict underneath.

## Foundational types

### Time

The canonical time coordinate is **absolute offset within a section**, as a `Fraction` of whole notes from section start. Bars and beats are *derived, per-voice views* computed from the section's meter. Harmonic events, analysis onsets, motif-entry positions, and feedback locations all store absolute offsets internally; bar/beat appears at the human and LLM surfaces.

This choice is bought for one future, cheaply: per-voice meters (polymeter) break every structure keyed by "bar number under the section's single meter", and re-keying the system later would touch everything. Absolute time is nearly free today, and it makes polymeter a contained extension (a per-voice meter field plus a notation strategy) instead of a rewrite. Polymeter itself remains unbuilt.

### Pitch

```python
class Pitch(BaseModel, frozen=True):
    step: Literal["C","D","E","F","G","A","B"]
    alteration: Fraction        # in whole tones: 1/2 = sharp, -1/2 = flat, 1/4 = quarter-sharp
    octave: int
```

Comparisons and range checks operate in cents. The ubiquitous 12-EDO view — pitch classes, semitone arithmetic, chord pitch-class sets — is a *derived view* of this type (`pitch.pc12`), not its definition. Surfaces use scientific ("G3") and LilyPond ("g") names, which parse into and print from `Pitch` losslessly for standard and quarter-tone alterations.

This keeps microtonality from being foreclosed at the type level. What is *not* built: microtonal audio (tuning tables, MTS) and any prompt surface for microtones — capability-gated out unless a spec requests them (see [04](04-generation-layers.md) on gating).

**M0 empirical answer — quarter-tones do reach MIDI as pitch bends.** LilyPond 2.26 emits a `pitchwheel` of ±2048 immediately before a quarter-tone note and resets it to 0 after: against the default ±2-semitone bend range, that is exactly ±50 cents. The microtonal door therefore stays open through the ordinary per-channel bend mechanism — the same one glissandi would use — rather than needing tuning tables. Two consequences the design inherits: a note's sounding pitch in score MIDI is its number *plus* the active bend, so any future microtonal analysis must read bend state (`NoteEvent` carries a `bend` field for this); and because bends are per channel, a *polyphonic* microtonal voice would need channel splitting, the same known ceiling the one-voice-one-channel invariant already has. Pinned by `test_quarter_tones_reach_midi_as_pitch_bends`.

### Meter

```python
class MeterTerm(BaseModel, frozen=True):
    numerator: int
    denominator: int            # powers of two only; irrational meters are a non-goal

class MeterSpec(BaseModel, frozen=True):
    terms: list[MeterTerm]      # one term = simple/compound meter; several = additive (3/4+1/8)
    grouping: list[int] | None  # beat grouping in shortest-term units, e.g. [2,2,3] for 7/8
```

Bar length is the exact `Fraction` sum of terms. The surface renders this as musicians write it: "7/8 (2+2+3)", "3/4+1/8".

**Assembler mapping, corrected against LilyPond 2.26.** A single term with a grouping is `\time #'(2 2 3) 7/8` — 2.26 carries the beat structure in `\time` itself, so the separate `\set Timing.beatStructure` this doc originally specified is unnecessary. Additive meters are `\timeAbbrev #'((3 4) (1 8))`: `\compoundMeter` was **renamed to `\timeAbbrev`** and no longer exists under the old name, so the original instruction would not have compiled. Both forms are exercised by `tests/fixtures/lily/satb_7_8_valid.ly`.

## `PieceSpec` — user intent

```python
class VoiceSpec(BaseModel):
    voice_id: VoiceId                      # "soprano", "bass", "violin1", …
    kind: Literal["vocal", "instrument"]
    group: str | None = None               # "concertino", "ripieno", "solo", …
    range_low: Pitch
    range_high: Pitch
    midi_program: int
    lyrics: bool = False

class PieceSpec(BaseModel):
    title: str
    style_prompt: str                      # free text: "Tool-inspired, dark, modal…"
    voices: list[VoiceSpec]
    meters_allowed: list[MeterSpec]        # the palette; plan may not exceed it
    key_center: str | None
    target_minutes: float
    tempo_bpm: int | None
    language: str | None = None            # lyric language, if vocal
```

Ranges are hard constraints — a note outside `[range_low, range_high]` is a validator failure, never a warning. `group` exists for ensemble-structure forms (concerto grosso's concertino/ripieno, antiphonal choirs): plans may address groups, and validators can check tutti/solo alternation deterministically. It is one optional field, not a hierarchy.

## `StylePack` — style as data

Generated once per run by an LLM node from `style_prompt`, then passed as context to every downstream generator and validator. This is what keeps the pipeline genre-agnostic: "Tool-inspired" is interpreted *once*, into concrete, checkable material, instead of every node re-interpreting a band name.

```python
class RhythmicCell(BaseModel):
    meter: MeterSpec
    lily: str                              # a one-bar LilyPond rhythm pattern
    description: str                       # "driving 2+2+3 eighths"

class StylePack(BaseModel):
    idioms: list[str]                      # prose directives: modes, texture habits…
    rhythmic_cells: list[RhythmicCell]     # vetted patterns generators may vary
    harmony_guidance: str
    parallel_fifths_policy: Literal["forbid", "allow", "encourage"]
    dissonance_policy: str
    dynamics_arc: str
    interpretation_defaults: InterpretationParams   # swing, offsets, curve intensity
    few_shot_fragments: list[str]          # short LilyPond examples in-style
```

The `rhythmic_cells` field is the odd-meter workhorse: generators build phrases by combining and varying vetted cells rather than inventing rhythm from nothing, which is where beat-count errors are born. Policies are read by validators — the same checker forbids parallels for a chorale and waves them through for a rock texture, driven by data. `interpretation_defaults` seeds the performance stage: a style implies a groove.

## `StructurePlan` — the formal map

```python
class DynamicsPlan(BaseModel):
    start: str                             # "pp"
    targets: list[DynTarget]               # [{bar: 9, level: "ff"}] — piecewise arc

class MaterialEntry(BaseModel):
    motif_id: MotifId
    voice_id: VoiceId
    bar: int                               # surface coordinate; parsed to offset
    relation: str                          # "exact", "P5 up", "tonal answer",
                                           #   "inversion", "octave down"…

class SectionPlan(BaseModel):
    section_id: SectionId
    bars: int
    meter: MeterSpec                       # one meter per section; meter *changes*
    key: str                               #   are modeled as section boundaries
    tempo_bpm: int
    texture: str                           # "homophonic", "imitative", "unison"…
    dynamics: DynamicsPlan
    active_voices: list[VoiceId | GroupRef]
    material: list[MaterialEntry] = []     # declared motif entries, if any
    intent: str                            # one sentence of musical purpose

class StructurePlan(BaseModel):
    sections: list[SectionPlan]
    materials_needed: list[MaterialBrief]  # what generate_motifs must produce
    form_summary: str
```

Two notes. `DynamicsPlan` is structured (not prose) because it is dual-projected: voice generators realize it as printed dynamics in the notation, and the interpretation stage realizes it as continuous CC curves in the audio. Both projections derive from the same plan; fine sub-arc shaping a generator adds in notation affects velocities only, and the critic is the loose check that print and sound agree. `MaterialEntry` is what makes strict forms enforceable — a fugue exposition is literally a list of declared entries with relations, which [05](05-verification-and-feedback.md) verifies against the compiled music.

Modeling a meter change as a section boundary is a deliberate simplification: it makes "does every bar match its meter?" decidable per section with one time signature in scope, at the cost of many short sections when meter shifts rapidly. If this proves too chatty, per-section meter *sequences* are the contained extension — contained precisely because internal time is absolute, not bar-keyed.

## `MotifLibrary` — material as state

```python
class Motif(BaseModel):
    motif_id: MotifId
    role: str                              # "fugue subject", "countersubject", "riff"
    lily_music: str                        # the material itself, as notation
    description: str

class MotifLibrary(BaseModel):
    motifs: dict[MotifId, Motif]
```

Motifs exist so "themes that return" is a checkable claim instead of an aspiration: an entry declared in the plan is verified as an interval-sequence relationship between the motif and the compiled music at that position ([05](05-verification-and-feedback.md)). At the LLM surface, motifs always travel as **verbatim notation with a musician's instruction** ("enter with this subject, real answer at the fifth"), never as bare ids — the id is bookkeeping for validators, the notes are for the composer.

## `HarmonicSkeleton` — per section

```python
class HarmonicEvent(BaseModel):
    offset: Fraction                       # internal: absolute, from section start
    duration: Fraction
    chord: str                             # "Dm", "Esus4/B", "D5"…

class HarmonicSkeleton(BaseModel):
    section_id: SectionId
    events: list[HarmonicEvent]            # gapless, ordered; validator-enforced
```

The *schema the LLM fills* speaks bar/beat (`{bar: 4, beat: 2.5, chord: "Esus4", duration_beats: 1.5}`); the parser converts to offsets, and the prompt builder converts back when showing context. Chord symbols are strings interpreted by the alignment validator through a small chord parser (root + quality + bass, yielding a pitch-class set via the 12-EDO view). The skeleton's own validator checks pure arithmetic — ordered, gapless, exactly filling the section — caught with exact fractions before any notation exists.

## `VoicePart` — the notation layer

```python
class TechniqueSpan(BaseModel):
    technique: str                         # from a controlled vocabulary: "sul pont.",
    from_bar: int                          #   "pizz.", "whispered", "gliss"…
    to_bar: int | None                     # None = point event

class VoicePart(BaseModel):
    section_id: SectionId
    voice_id: VoiceId
    lily_music: str                        # the music expression
    lily_lyrics: str | None                # \lyricmode block, if vocal
    techniques: list[TechniqueSpan] = []   # structured copy for the audio path
```

### Fragment conventions (the generator contract)

These conventions exist because each one converts a common LLM failure into a machine-detectable error — and they are a *disciplined subset of textbook LilyPond*, never a house dialect. Everything a generator writes, it has seen thousands of times in training data; any convenience macro or custom scaffolding lives in the assembler where no LLM reads or writes it. That asset is protected deliberately (see [08](08-engineering-principles.md), principle 2).

1. **Absolute pitch only** (`\absolute`, explicit octave marks). `\relative` mode makes every pitch depend on the previous one — a single octave slip silently transposes the rest of the line. Absolute pitch makes errors local.
2. **A bar check `|` at every barline.** The LilyPond compiler then reports every bar whose contents don't fill the meter, with a bar number. This is the meter validator — the compiler does the duration arithmetic, and the pipeline never needs its own LilyPond duration parser.
3. **No structural commands in fragments.** No `\score`, `\layout`, `\time`, `\tempo`, `\clef` — assemblers own structure; fragments are pure music expressions. This is what makes deterministic assembly possible.
4. **Explicit durations on every note** (no duration carry-over), same rationale as absolute pitch: no hidden state between tokens.
5. **Lyrics in `\lyricmode` with explicit syllable alignment** (`--`, `__`), validated by compiling (LilyPond warns on note/syllable count mismatch).

    *Extended in implementation.* Words are no longer written by the voice call at all. They come from a dedicated lyric layer, after the music, one call per section covering every singing voice — see [10](10-lyrics.md) for why coordination cannot be prompted into a per-voice call. The surface is the same lyricmode convention, written as lines: `"sha -- dow on the wa -- ter __"`. Our parser tokenizes those (whitespace split, `--` joins, `__` extenders — a token scan, never a parser) and renders the `\lyricmode` block itself, so the block is well-formed whatever came back. Bar checks are stripped from lyrics rather than enforced: inside `\lyricmode` a `|` is a bar check, and one mirrored across from the music passes in a single-section scaffold and fails after concatenation.
6. **Nested tuplets and dynamics are plain LilyPond** (`\tuplet`, `\p`, `\<`) — fully in scope, no special handling; the compiler's arithmetic covers arbitrary tuplet nesting.
7. **Technique markings appear twice by design:** as standard markup in the notation (for the score) and as the structured `techniques` list in the tool call (for the audio mapping). The structured copy drives interpretation; divergence between the two is cosmetic-risk only and left to the critic — a cross-checker here would be a LilyPond parser through the back door.

### Assembly

`assemble_section` and `assemble_score` are pure functions that wrap fragments in deterministic scaffolding: voice variables (`musicA1Soprano`), staves and staff groups from `PieceSpec.voices`, `\time`/`\compoundMeter`/`\tempo`/`\key` from the plan, `\midi {}` and `\layout {}` blocks.

**Hard invariant: one voice = one MIDI track = one MIDI channel.** The analysis validators key on it, and every per-channel MIDI mechanism the performance stage uses — pitch bend for glissandi and microtones, per-voice CC dynamics, per-voice timing offsets — is only possible because of it. The assembler owns this invariant; breaking it breaks two subsystems at once. (Its known ceiling: *polyphonic* continuous pitch within one voice, e.g. divisi glissando, would need channel splitting — a contained future exactly because the invariant is explicit.)

**M0 empirical answer — the invariant holds, and here is the recipe.** Wrapping each staff's music in `\new Voice = "<voice_id>"` and setting `midiChannelMapping = #'staff` in the `\midi` block gives every voice its own track on its own channel. Two details the analysis path depends on: LilyPond names each track `<staff>:<voice_id>`, so **the voice id is recoverable from the track name** — the reliable key, rather than channel order; and channels are **distinct but not contiguous** (SATB with lyrics yields 0, 2, 3, 4, because a `Lyrics` context consumes a channel number), so nothing may assume `0..n-1`. The mapping happens to be the 2.26 default, but the assembler sets it explicitly so the invariant is declared rather than inherited. Pinned by `test_one_voice_is_one_track_on_one_channel` and `test_voice_channels_are_distinct_but_not_contiguous`.

## `InterpretationParams` — the performance domain's knobs

```python
class InterpretationParams(BaseModel):
    swing: dict[SectionId, float] = {}         # ratio; absent = straight
    voice_offset_ms: dict[VoiceId, float] = {} # laid-back / pushed feel
    dynamics_curve_intensity: float = 1.0      # scaling of DynamicsPlan → CC curves
    technique_mappings: dict[str, MidiAction] = {}  # technique → program/CC change
```

Read by `interpret_performance` (score MIDI in, performance MIDI out — pure given its inputs). Defaults come from `StylePack.interpretation_defaults`; the critique loop may adjust them, which is why they live in pipeline state. v1 implements `DynamicsPlan`→CC curves fully (hairpins on held chords are inaudible without it) and identity for the rest; swing, offsets, bend synthesis, and technique mappings fill in behind the same seam as needs demonstrate.

**M0 empirical answer — the SoundFont honors CC11.** FluidR3_GM under FluidSynth 2.5.7 renders a held note at expression 127 with roughly 40× the RMS amplitude of the same note at expression 20, so the dynamics-curve mechanism the whole score/performance split is justified by does work end to end. This check was pulled forward from the performance milestone deliberately: a SoundFont that ignored expression would have invalidated a design commitment while failing silently — the audio would simply have been flat. Pinned by `test_the_soundfont_actually_responds_to_expression`.

## `RenderedArtifacts`

```python
class RenderedArtifacts(BaseModel):
    lily_path: Path            # canonical source
    pdf_path: Path             # engraved score
    score_midi_path: Path      # LilyPond's compilation — what validators analyze
    performance_midi_path: Path# interpreted — what FluidSynth renders
    audio_path: Path
```

The dependency direction is absolute: LilyPond source → score artifacts → performance artifacts. No artifact is ever edited downstream; any fix loops back to the layer that owns the mistake — notation errors to generation, performance qualities to `InterpretationParams` — and everything downstream regenerates. MusicXML export can be added later as one more derived artifact behind the renderer boundary; nothing else would change.

## Why LilyPond, restated as requirements

Plain text (LLM-writable, diffable, and — decisively — the notation format with the deepest training-data presence); professional engraving including full choral support (SATB, lyrics, divisi, melismas) and extended-technique markup; native arbitrary, compound, and additive meters with explicit beat grouping; native quarter-tone accidentals; polymetric notation possible (per-Staff timing) should that extension ever open; compiles to both score and MIDI from one source, guaranteeing their agreement; a compiler whose error messages double as free validation. The considered alternatives fail at least one hard requirement: ABC is weak on complex meter and choral layout; MusicXML is too verbose for reliable LLM generation (though fine as an export); a bespoke JSON note-list IR would have the *least* training-data density of any option — the exact opposite of what the quality ceiling demands; audio-first models provide no notation at all.
