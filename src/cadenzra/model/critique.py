"""What the audio critic is asked, and what it answers with.

The critic is holistic by design: it catches "the middle is mud" and "the meter
doesn't groove", not "parallel fifth in bar 37". Precise diagnostics are the
deterministic validators' job, and asking an audio model for them produces
confident nonsense (docs/05).
"""

from pydantic import BaseModel, Field

from cadenzra.model.primitives.ids import SectionId, VoiceId


class CritiqueBrief(BaseModel, frozen=True):
    """What the piece was trying to be, so the critic can judge it against that."""

    title: str
    intent: str
    form_summary: str
    sections: list[str] = Field(default_factory=list)
    voices: list[VoiceId] = Field(default_factory=list)
    style: str = ""
    dynamics_arc: str = ""


class Observation(BaseModel, frozen=True):
    """One thing the critic heard, localized as far as it honestly can be."""

    concern: str
    section_id: SectionId | None = None
    voice_ids: list[VoiceId] = Field(default_factory=list)
    severity: int = 3


class CritiqueVerdict(BaseModel, frozen=True):
    """The critic's report on a rendered performance."""

    overall: str = ""
    acceptable: bool = True
    observations: list[Observation] = Field(default_factory=list)
