"""Compiler results and the artifacts a finished run emits.

The dependency direction is absolute: LilyPond source → score artifacts →
performance artifacts. No artifact is ever edited downstream of its source
(docs/03).
"""

from pathlib import Path

from pydantic import BaseModel, Field

from cadenzra.model.primitives.ids import SectionId, VoiceId


class BarCheckWarning(BaseModel, frozen=True):
    """One "barcheck failed" from the compiler.

    LilyPond reports a source line and column, not a bar number; deriving the
    bar is `notation/scaffold.py`'s job, because only the scaffolder knows how
    the fragment was wrapped.
    """

    line: int
    column: int
    message: str
    file: str = ""


class CompileResult(BaseModel, frozen=True):
    """What one LilyPond invocation produced.

    `ok` means the compiler exited zero and its artifacts exist. Bar-check
    failures do *not* clear that flag — LilyPond exits zero on them — so
    validators require `ok and not bar_check_warnings` (docs/05).
    """

    ok: bool
    pdf_path: Path | None = None
    midi_path: Path | None = None
    bar_check_warnings: list[BarCheckWarning] = Field(default_factory=list)
    raw_output: str = ""

    @property
    def clean(self) -> bool:
        """Compiled *and* every bar filled its meter."""
        return self.ok and not self.bar_check_warnings


class RenderedArtifacts(BaseModel, frozen=True):
    """The five mutually-consistent outputs of a completed run."""

    lily_path: Path
    pdf_path: Path
    score_midi_path: Path
    performance_midi_path: Path
    audio_path: Path


class AssembledSection(BaseModel, frozen=True):
    """One section's voices wrapped in deterministic scaffolding."""

    section_id: SectionId
    lily_source: str
    voice_order: list[VoiceId] = Field(default_factory=list)


class AssembledScore(BaseModel, frozen=True):
    """The canonical LilyPond file — the source of truth for everything else."""

    lily_source: str
    section_order: list[SectionId] = Field(default_factory=list)
    voice_order: list[VoiceId] = Field(default_factory=list)
