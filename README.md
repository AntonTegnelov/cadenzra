# Cadenzra

Cadenzra is a tool for musicians who want AI support in their creative process
without giving up the score. You describe a piece — the ensemble and its
ranges, the meters, the style, the length — and it drafts real, engraved sheet
music: something you can rehearse from, mark up, rewrite, and make your own.
The AI does the sketching; the musical judgment stays with you.

```bash
cadenzra compose tool-choir
```

Out comes a PDF score, the LilyPond source it was engraved from, score MIDI, an
interpreted performance MIDI, and audio so you can hear the draft — five
artifacts that always agree, because they all descend from one notation file.

## Notation first

Most AI music tools are audio-first: you get a recording, and the notation —
the thing a musician actually works with — is nearly unrecoverable from it.
Cadenzra inverts that. The score is the source of truth and everything else is
compiled from it, so what you hear is exactly what is on the page. The LilyPond
source is yours: change a phrase, re-engrave, re-render, and score and audio
can never disagree.

## A draft you can trust

A plausible-looking but wrong score wastes a rehearsal. So Cadenzra
machine-checks every draft before handing it over: every bar fills its declared
meter (decided by LilyPond's own bar checks), every note stays inside the range
you declared for each voice or singer, and material the plan says returns — a
fugue subject, a riff — verifiably returns, checked against the compiled music
itself. When the system can't produce a correct result, it says so and stops,
leaving everything it produced for inspection. It never pads a bar, transposes
away a range violation, or silently drops a section to force completion.

What the checks deliberately do *not* decide is taste. Validators check
arithmetic, ranges, and declared relationships; whether the music is any good
is a judgment the tool leaves where it belongs — with you.

## What it can take on

- **Odd, shifting, and additive meters** — 5/4, 7/8 with explicit groupings
  (2+2+3 vs 3+2+2), 3/4+1/8, meter changes between sections. Irregular meter is
  where AI-written notation most often breaks, so the whole pipeline is built
  around getting it right.
- **Any style, as data.** Style enters as a free-text prompt that is
  interpreted once into concrete idioms, rhythmic cells, and constraints. The
  built-in specs range from a Tool-inspired SATB choral piece through fugues,
  minimalism, orchestra, metal, and synthwave — none has a code path of its own.
- **Long-form structure.** Pieces are planned top-down — form, then harmony,
  then voices — so sections relate and themes return instead of the music
  wandering.
- **Lyrics that hold together.** Words are written per section, for all singing
  voices in one pass, after the music exists — fitted to the notes, coordinated
  across parts, with rhyme schemes and refrains checked.
- **Audio you can evaluate.** A deterministic performance stage turns the score
  into a shaped rendering — continuous dynamics so a held-chord crescendo is
  audible, not merely printed.

## Where you come in

The rendered audio is a compositional proof, not a production track — FluidSynth
with a General MIDI SoundFont sounds synthetic on purpose. The real performance
is yours: hand the PDF to your choir, pull the MIDI into your DAW under real
instruments, or treat the whole draft as the sketch your piece grows out of.
Cadenzra's job ends where the interesting work begins.

## How it works

Generation runs top-down through abstraction layers, each producing a compact
artifact that constrains the next: a style pack, a formal plan, reusable motifs,
a harmonic skeleton per section, then one voice's notation at a time. Each layer
is verified **at the level it was produced**, and failures route back to the
smallest unit that can fix them — a wrong beat count in the alto's bars 9–12
regenerates four bars of one voice, not the section and not the piece.

Verification leans on two mature externalities rather than home-grown parsers.
LilyPond's own bar checks decide whether every bar fills its meter, and its
compiled MIDI is what pitch-and-timing analysis reads: **Cadenzra never parses
LilyPond notation itself**. What remains is small and decidable — exact
`Fraction` arithmetic, range checks in cents, interval-sequence comparison for
declared motif entries.

The score domain ends at score MIDI. A separate deterministic stage turns that
into a *performance* — continuous dynamics curves, and the seam where swing and
micro-timing will live — which is why a held-chord crescendo is audible rather
than merely printed, and why "sounds stiff" costs a re-render instead of a
rewrite.

## Describing a piece

A piece is a `PieceSpec`: the voices with their kinds and ranges, the meters the
plan may use, a free-text style prompt, a target duration, and a lyric language
if anything sings. The built-in specs live in
[src/cadenzra/app/specs.py](src/cadenzra/app/specs.py) — `smoke` is the small,
fast one; `tool-choir` is the full choral commission. Describing your own piece
is adding a spec there.

## Documentation

The design is documented in full under [docs/](docs/), best read in order.
[01 — Vision & Scope](docs/01-vision-and-scope.md) states what the tool is for
and what it deliberately does not do; [08 — Engineering
Principles](docs/08-engineering-principles.md) is the shortest route to how the
code is meant to be written.

Empirical results — including two findings that corrected the design — are in
[docs/harness-results/](docs/harness-results/).

## Working on it

The devcontainer carries the whole toolchain: Python 3.14, LilyPond 2.26,
FluidSynth 2.5, and a General MIDI SoundFont.

```bash
uv sync --dev
```

```bash
uv run pytest
```

Unit tests are pure — values in, values out, no compiler and no model — and
cover the layer that carries the correctness guarantees. Integration tests run
the real binaries:

```bash
uv run pytest -m integration
```

Both must pass, along with `uv run mypy` and `uv run ruff check`, before a
milestone is considered done.

Prompt quality can only be measured against a real model, so it is measured
rather than assumed:

```bash
uv run cadenzra harness voice --meter 7/8 --trials 10 --ab
```

Results land in `docs/harness-results/` so regressions are visible.

## Configuration

A `GEMINI_KEY` in `.env` at the repository root is all a live run needs. Gemini
backs both the generator and the audio critic in v1; every external system sits
behind a protocol in `src/cadenzra/interfaces/`, wired in one factory, so adding
a provider is a client, a service, and a line in `app/factory.py`.
