"""Protocols for the two external programs the pipeline drives.

These mark genuine externality — a vendor or a binary that tests must be able
to replace — not "things that feel important" (docs/08, principle 5). The
interpretation transform deliberately has no protocol: it is deterministic
internal code with nothing to swap and no non-determinism to fake.
"""

from pathlib import Path
from typing import Protocol

from cadenzra.model.artifacts import CompileResult
from cadenzra.model.spec import VoiceSpec


class ScoreRenderer(Protocol):
    """LilyPond. One `compile` serves both scaffolded fragment validation and
    final rendering — one boundary, one behavior, exercised constantly rather
    than only at the end of a run (docs/06)."""

    def compile(self, lily_source: str, workdir: Path) -> CompileResult: ...


class Synthesizer(Protocol):
    """FluidSynth: performance MIDI in, audio out."""

    def render(self, midi: Path, voices: list[VoiceSpec], out: Path) -> Path: ...
