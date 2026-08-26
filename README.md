# Cadenzra

Cadenzra is a tool for musicians who want AI in their creative process without
giving up the score. The AI is built to take a piece end to end — concept,
composition, performance — but the point is that *you choose what to delegate*.
Keep the composing and hand off the performing, or the reverse; sketch a
skeleton and have the AI flesh it out; or let it draft the whole piece and
treat the result as your starting point.

```bash
cadenzra compose tool-choir
```

Out comes a PDF score, its LilyPond source, score MIDI, an interpreted
performance MIDI, and audio — five artifacts that always agree, because they
all descend from one notation file.

## Notation first

Most AI music tools are audio-first: you get a recording, and the notation —
the thing a musician actually works with — is nearly unrecoverable from it.
Cadenzra inverts that. The score is the source of truth, everything else is
compiled from it, and the LilyPond source is yours to edit.

## A draft you can trust

Every draft is machine-checked before it reaches you: every bar fills its
declared meter (decided by LilyPond's own bar checks), every note stays inside
each voice's declared range, and material the plan says returns — a fugue
subject, a riff — verifiably returns. When the system can't produce a correct
result it stops and says so, leaving partial artifacts for inspection; it never
pads a bar, transposes away a range violation, or drops a section to force
completion. What the checks never decide is taste — that stays with you.

## What it can take on

- **Odd, shifting, and additive meters** — 5/4, 7/8 with explicit groupings,
  3/4+1/8 — the place AI-written notation most often breaks.
- **Any style, as data.** A free-text style prompt is interpreted once into
  concrete idioms and constraints; the built-in specs range from a
  Tool-inspired SATB choir to fugues, orchestra, metal, and synthwave.
- **Long-form structure** — planned top-down so sections relate and themes
  return.
- **Coordinated lyrics** — written per section for all voices at once, fitted
  to the finished music.
- **Expressive audio** — a deterministic performance stage renders dynamics
  curves, so a held-chord crescendo is audible, not merely printed.

## Where it's going

v1 is a batch pipeline: spec in, artifacts out, with editing done by hand on
the LilyPond source afterwards. The roadmap (work in progress):

- **Manual editing at every layer** — plan, harmony, voices, score,
  performance — with the AI rebuilding everything downstream of your edit.
- **A real production stage** — piping the performance MIDI into a fully
  featured DAW (homebrewed, or open-source such as openDAW or Ardour, possibly
  a fork), under the same notation-first philosophy.

The goal is that every division of labor works: AI end to end, human end to
end, and everything in between.

## Describing a piece

A piece is a `PieceSpec`: voices with ranges, allowed meters, a style prompt, a
target duration, and a lyric language if anything sings. Built-in specs live in
[src/cadenzra/app/specs.py](src/cadenzra/app/specs.py) — `smoke` is the small
fast one, `tool-choir` the full choral commission. Your own piece is a spec
added there.

## Documentation

The design docs are under [docs/](docs/), best read in order.
[01 — Vision & Scope](docs/01-vision-and-scope.md) states what the tool is for;
[08 — Engineering Principles](docs/08-engineering-principles.md) how the code is
meant to be written. Empirical results, including two findings that corrected
the design, are in [docs/harness-results/](docs/harness-results/).

## Working on it

The devcontainer carries the whole toolchain: Python 3.14, LilyPond 2.26,
FluidSynth 2.5, and a General MIDI SoundFont.

```bash
uv sync --dev
```

```bash
uv run pytest
```

Unit tests are pure — no compiler, no model. Integration tests
(`uv run pytest -m integration`) run the real binaries. Both must pass, along
with `uv run mypy` and `uv run ruff check`. Prompt quality is measured against
a real model, not assumed:

```bash
uv run cadenzra harness voice --meter 7/8 --trials 10 --ab
```

## Configuration

A `GEMINI_KEY` in `.env` at the repository root is all a live run needs. Every
external system sits behind a protocol in `src/cadenzra/interfaces/`, wired in
one factory, so adding a provider is a client, a service, and a line in
`app/factory.py`.
