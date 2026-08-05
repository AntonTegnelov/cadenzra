# Cadenzra

Cadenzra composes complete musical works with AI, where the primary artifact is
**correct sheet music** and audio is derived from it. This inverts the common
approach — audio-first tools, from which notation is nearly unrecoverable. Here
the score *is* the source of truth, and everything else is compiled from it, so
sheet music and audio can never disagree.

```bash
cadenzra compose tool-choir
```

Out comes a PDF score, the LilyPond source it was engraved from, score MIDI,
an interpreted performance MIDI, and audio — five artifacts that agree because
they descend from one text file.

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

## Documentation

The design is documented in full under [docs/](docs/), best read in order.
[01 — Vision & Scope](docs/01-vision-and-scope.md) states what the system is for
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
