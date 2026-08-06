# Working on Cadenzra

The design docs under `docs/` are authoritative and were written before the
code. Read the relevant one before changing behaviour they describe; where
implementation has since corrected a doc, the doc says so inline and points at
the evidence.

## Commands

```bash
uv sync --dev
```

- `uv run pytest` — unit tests, no compiler, no model, no network.
- `uv run pytest -m integration` — real LilyPond and FluidSynth.
- `uv run mypy` and `uv run ruff check` — both must be clean.
- `uv run cadenzra compose <spec>` — a full live run (`smoke` is the fast one).
- `uv run cadenzra harness voice --meter 7/8 --trials 10 --ab` — measure prompt
  quality against the real model.

## The two rules that shape everything

**Notation is the source of truth.** Audio is compiled from the score, never the
reverse, and no artifact is edited downstream of its source. A fix loops back to
the layer that owns the mistake and everything after it is rebuilt.

**Exotic internals, musician surface.** Internally, time is an exact `Fraction`
offset and pitch is tuning-agnostic. Everything an LLM reads or writes speaks
bars, beats, note names, chord symbols and textbook LilyPond, because that is
where the model's compositional ability lives. The translation happens in
`llm/prompts/` and `llm/parsers/` and **nowhere else** — a `Fraction` in a
prompt, or a bar number in `verification/` logic, is a bug.

## Things that will bite

- **Never parse LilyPond.** Pitch and timing analysis reads the *compiled MIDI*;
  meter correctness comes from the compiler's bar checks. The only text scans
  allowed are token-level ones that no parser is needed for: the structural
  command denylist, counting `|`, reading a first pitch.
- **One voice = one track = one channel.** `notation/assemble.py` owns this.
  Track names carry the voice id (that is the reliable key — channels are
  distinct but *not* contiguous), and every per-voice performance mechanism
  depends on it.
- **Never guess a diagnosis when the real one is available.** A validator that
  paraphrases a compiler failure sends the regeneration looking in the wrong
  place, and it will spend its whole budget there. Quote the compiler.
- **Feedback must reach the regeneration.** Every layer that retries has to put
  its rejection reasons into the next prompt, or it produces the same mistake
  rephrased until the budget runs out. There is a test asserting this.
- **Do not let validators legislate taste.** docs/01 rules out a general
  music-theory engine. Checks decide arithmetic, ranges, and declared
  relationships. "Is this a good chord" is not one of them.
- **Lyrics are written per section, after the music, in one call for every
  singing voice.** Never re-add per-voice lyric generation: voices that cannot
  see each other's words invent separate texts, and that produced a piece with
  one voice in Latin over another in English. See `docs/10-lyrics.md`.

- **Do not give an LLM judge the answer key.** The audio critic's brief
  deliberately withholds what the piece was trying to be; told the intended
  shape, it reports hearing that shape whether or not it is there. See
  `docs/harness-results/`.

## Failure is loud

When a retry budget runs out the run ends non-zero, with everything produced so
far written to the output directory. The pipeline never pads a bar, transposes
away a range violation, or drops a section to force completion — a
plausible-looking but wrong score is the one output this system exists to
prevent, because the human downstream trusts the artifact.
