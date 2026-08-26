# 01 — Vision & Scope

## Purpose

Cadenzra is a tool for musicians: it uses AI to support the creative process by drafting complete musical works whose primary artifact is **correct sheet music** — notation a musician can rehearse from, edit, and build on — with audio derived from it. This inverts the common approach (audio-first tools like Suno, which hand a musician a recording from which notation is nearly unrecoverable): here the score *is* the source of truth, and everything else — MIDI, audio — is compiled from it. Sheet music and audio can never disagree, because they are renderings of one text file.

The division of labor is deliberate and runs through the whole design: the system owns the mechanical guarantees (bars that fill their meters, parts inside their ranges, themes that verifiably return), and the musician owns the music. Validators decide arithmetic, never taste; the final judgment on whether a draft is any good — and everything downstream of the draft, from real performance to rewriting half of it — belongs to the human.

## Hard requirements

**Correct, complete sheet music.** Not approximate transcription — engraved notation that a musician or choir could rehearse from: proper voicing, lyrics aligned to notes, dynamics, tempo and meter markings.

**Odd, shifting, and additive time signatures.** 5/4, 7/8, alternating meters, additive signatures (3/4+1/8), and explicit beat-grouping within them (3+2+2 vs 2+2+3 in 7/8 are different musical statements and must be representable and controllable). This requirement drives several design choices, because irregular meter is precisely where LLM-generated notation most often breaks.

**Genre-generality.** The architecture is style-agnostic. Style enters the system as *data* — a configuration of idioms, constraints, and few-shot material — never as hardcoded logic. The first production run is a Tool-inspired choral piece; the second could be a fugue for string quartet or a synthwave track without touching pipeline code.

**Long-form coherence, including recurring material.** LLMs write plausible four-bar phrases and incoherent sixty-bar pieces. The system must produce works with real formal structure — sections that relate, themes that verifiably return (up to and including strict forms like fugue), an arc — which is why generation is layered top-down and why thematic material is first-class state rather than hope ([02](02-architecture-overview.md), [04](04-generation-layers.md)).

**Musically expressive audio.** Rendered audio must realize the score's *musical* content, not just its notes: a crescendo on a held chord must be audible, swing and groove must be applicable where the style calls for it. This is what the performance-interpretation stage exists for ([02](02-architecture-overview.md)) — and it is distinct from *production-quality* audio, which remains a non-goal.

**LLM-intuitive surfaces.** The quality ceiling of the whole system is the LLM's compositional ability, which rests on training-data density. Every representation an LLM reads or writes must therefore be maximally conventional — bar numbers, beats, standard note names, textbook LilyPond — regardless of how the system represents things internally. This is a hard requirement, not a style preference; it is principle 2 in [08](08-engineering-principles.md).

## First milestone piece

A Tool-inspired work for SATB choir: shifting odd meters, modal harmony (Lydian/Phrygian colorings), alternation between rhythmic-unison "heavy" passages and polyphonic quiet ones, long held-chord crescendos, a long dynamic arc. This piece is the acceptance test for the whole pipeline — it exercises every hard requirement at once, deliberately, including the performance stage (those held-chord crescendos are inaudible without it).

## Non-goals

**Production-quality audio.** FluidSynth with a choir SoundFont sounds synthetic. That is acceptable: the audio output is a *compositional proof* — correct notes, rhythms, balance, and musical shaping — not a release-ready recording. Convincing performance (VST choirs, a DAW, human singers reading the PDF) is downstream of this system.

**Realistic audio for extended techniques.** Extended techniques (sul ponticello, whispered tone, vocal fry) are notated correctly in the score; their audio realization degrades gracefully to approximate timbres or plain playback depending on what the SoundFont and interpretation mappings offer. Score correct, audio approximate — by design.

**Polytempo.** Genuinely independent simultaneous tempi is out of reach of the entire toolchain: LilyPond cannot meaningfully notate it, standard MIDI has a single tempo map, and the proportional-notation workarounds would distort every layer. Explicitly forecloseed.

**Irrational meters.** Time signatures with non-power-of-two denominators (e.g. 4/3) are a poorly-supported LilyPond hack. Foreclosed. (Additive and compound meters are *in* scope — see requirements.)

**Live or interactive performance.** The pipeline is batch: spec in, artifacts out. (A Strudel export could be added later as an alternative renderer behind the same boundary as FluidSynth; nothing is built for it now.)

**A general music-theory engine.** Validators check specific, decidable properties (bar arithmetic, ranges, parallels, harmonic alignment, transposition relationships between motif entries). They do not attempt to formalize "good music." Aesthetic judgment stays with LLM critique nodes and, ultimately, the human reviewing the output.

**Audio-to-notation.** The system never transcribes audio. Data flows one direction: notation → audio.

## Success criteria

1. Given a `PieceSpec`, the pipeline runs to completion unattended and emits mutually consistent artifacts: PDF score, score MIDI, performance MIDI, audio file, LilyPond source.
2. Every bar in the score satisfies its declared meter; every part stays in its range; declared motif entries verifiably relate to their motifs; the compiled score has zero LilyPond errors. These are machine-checked, not hoped for.
3. The Tool-inspired choir piece is judged musically coherent by its human commissioner — sections relate, the meter shifts feel intentional, the dynamics *sound* (not just print), the style directives are audible.
4. Swapping the target style requires editing only configuration/style data, not pipeline code.

## Constraints & context

The implementation is Python. Orchestration is LangGraph — chosen because the design's core mechanic is *conditional feedback loops between many nodes*, which is exactly the shape LangGraph models well; a linear script would reimplement half of it badly. Generation LLMs and the audio-critique LLM are accessed through provider-agnostic protocols ([06](06-boundaries-llm-and-rendering.md)); the initial wiring uses Claude for text/notation generation and Gemini for audio understanding, but nothing outside the client adapters knows that. (*Corrected in implementation:* Gemini backs both roles in v1 — `GeminiGenerator` and `GeminiCritic` in `llm/services/` — which is itself a demonstration of the boundary: the swap touched no pipeline code.)
