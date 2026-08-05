"""The inputs each generator needs, as data.

Protocols speak musical intent rather than transport (docs/06), so each
generation method takes one of these — assembled by the node, translated to a
prompt by the adapter. Nothing here is prompt text; nothing here is internal
coordinates leaking outward either. This is the boundary's vocabulary.
"""

from pydantic import BaseModel, Field

from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.harmony import HarmonicSkeleton
from cadenzra.model.motif import Motif
from cadenzra.model.spec import PieceSpec, VoiceSpec
from cadenzra.model.structure import (
    MaterialBrief,
    MaterialEntry,
    SectionPlan,
    StructurePlan,
)
from cadenzra.model.style import StylePack
from cadenzra.model.voice import VoicePart


class MaterialInstruction(BaseModel, frozen=True):
    """A motif entry as the composer should receive it.

    Motifs travel as verbatim notation with a musician's instruction, never as
    bare ids — the id is bookkeeping for validators, the notes are for the
    composer (docs/03).
    """

    motif: Motif
    entry: MaterialEntry


class MotifContext(BaseModel, frozen=True):
    """Everything needed to write the piece's recurring material.

    The plan and spec travel together because range-fit is checked *under every
    declared relation*: a subject is only writable once you know which voices
    carry it and how it is transformed when they do (docs/04).
    """

    briefs: list[MaterialBrief]
    spec: PieceSpec
    style: StylePack
    plan: StructurePlan
    feedback: list[FeedbackItem] = Field(default_factory=list)


class HarmonyContext(BaseModel, frozen=True):
    """One section's harmony, with the previous section's tail for continuity."""

    section: SectionPlan
    style: StylePack
    motifs: list[Motif] = Field(default_factory=list)
    previous_section: SectionPlan | None = None
    previous_skeleton: HarmonicSkeleton | None = None
    feedback: list[FeedbackItem] = Field(default_factory=list)


class VoiceContext(BaseModel, frozen=True):
    """Everything needed to write one voice's music for one section.

    Deliberately small: one voice x one section is typically 8-24 bars of a
    single line, comfortably inside the window where LLM notation stays
    accurate. The whole layered design exists so this call can be this small
    (docs/04).
    """

    section: SectionPlan
    voice: VoiceSpec
    style: StylePack
    skeleton: HarmonicSkeleton | None = None
    materials: list[MaterialInstruction] = Field(default_factory=list)
    # The last few bars this same voice sang in the previous section, so lines
    # connect across boundaries.
    previous_tail: str | None = None
    # On a regeneration: the fragment that was rejected, and why.
    rejected: VoicePart | None = None
    feedback: list[FeedbackItem] = Field(default_factory=list)

    @property
    def is_regeneration(self) -> bool:
        return self.rejected is not None
