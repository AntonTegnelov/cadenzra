"""The inputs each generator needs, as data.

Protocols speak musical intent rather than transport (docs/06), so each
generation method takes one of these — assembled by the node, translated to a
prompt by the adapter. Nothing here is prompt text; nothing here is internal
coordinates leaking outward either. This is the boundary's vocabulary.
"""

from fractions import Fraction

from pydantic import BaseModel, Field

from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.harmony import HarmonicSkeleton
from cadenzra.model.lyrics import SectionLyricDirective, SectionLyrics
from cadenzra.model.motif import Motif
from cadenzra.model.primitives.ids import VoiceId
from cadenzra.model.primitives.meter import MeterSpec
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
    # The meter the motif is written in. When it differs from the entry
    # section's meter, the prompt must teach ties across barlines — the only
    # way to keep every note value exact in the foreign meter.
    home_meter: MeterSpec | None = None
    # The entry rendered ready to copy: realized under its relation, shifted
    # into the voice's range by whole octaves, rebarred into the section's
    # meter. None when the events are unavailable or unrepresentable — the
    # prompt then falls back to instruction text.
    prescribed_lily: str | None = None
    # The bars the prescription occupies, for the patch permission model.
    prescribed_bars: tuple[int, ...] = ()
    # How much of the final prescribed bar is left for the composer to
    # write, when the entry ends mid-bar. None when every bar is complete.
    open_remainder: Fraction | None = None
    # Tonal answers may adjust this many notes by a step; 0 elsewhere.
    max_adjustable: int = 0


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


class PinnedTone(BaseModel, frozen=True):
    """One sustained entry note the grid must fit.

    Realized under the entry's relation and placed at its bar — fixed before
    any harmony is written, because the entry cannot change. A fugue
    exposition pins tones in every voice at once, and a model shown them
    only as violations fixes one and breaks another until the budget dies.
    """

    voice_id: VoiceId
    midi_pitch: int
    # Offset from the section start, and how long the note sounds.
    onset: Fraction
    duration: Fraction


class HarmonyContext(BaseModel, frozen=True):
    """One section's harmony, with the previous section's tail for continuity."""

    section: SectionPlan
    style: StylePack
    motifs: list[Motif] = Field(default_factory=list)
    pinned: list[PinnedTone] = Field(default_factory=list)
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
    # connect across boundaries — and the meter they were written in, because
    # a tail shown without its meter teaches the old bar length by example.
    previous_tail: str | None = None
    previous_meter: MeterSpec | None = None
    # On a regeneration: the fragment that was rejected, and why.
    rejected: VoicePart | None = None
    feedback: list[FeedbackItem] = Field(default_factory=list)
    # The other voices' music in this section, shown only when the rejection
    # is *about* them. First-pass generation stays independent given the
    # skeleton (docs/04); a cross-voice repair cannot be, because the fault is
    # a relationship and the fix has to be measured against the other line.
    siblings: dict[VoiceId, str] = Field(default_factory=dict)

    @property
    def is_regeneration(self) -> bool:
        return self.rejected is not None


class LyricsContext(BaseModel, frozen=True):
    """Everything needed to write one section's words — for every voice at once.

    Deliberately *not* per-voice. Coordination between singers is the thing
    this layer exists to guarantee, and a per-voice call cannot guarantee it
    however well it is prompted (docs/10).
    """

    section: SectionPlan
    directive: SectionLyricDirective
    language: str
    story: str
    voice_ids: list[VoiceId] = Field(default_factory=list)
    # The music these words are being set to, already validated.
    parts: dict[VoiceId, VoicePart] = Field(default_factory=dict)
    # Earlier sections' words, so this one continues them.
    previous: list[SectionLyrics] = Field(default_factory=list)
    # When this section declared itself a refrain, the words it brings back.
    refrain_source: SectionLyrics | None = None
    rejected: SectionLyrics | None = None
    feedback: list[FeedbackItem] = Field(default_factory=list)


class PatchContext(BaseModel, frozen=True):
    """Everything needed to rewrite only the flagged bars of one part.

    `editable_bars` is the whole permission model: a bar not in it — a
    prescribed entry, or simply an unflagged bar — is not offered, so a patch
    cannot break what a validator did not complain about. That is the
    structural fix for repairs that "fixed" a parallel by rewriting the
    subject (the double-fugue's oscillation).
    """

    section: SectionPlan
    voice: VoiceSpec
    skeleton: HarmonicSkeleton | None = None
    part: VoicePart
    editable_bars: tuple[int, ...]
    feedback: list[FeedbackItem] = Field(default_factory=list)
    siblings: dict[VoiceId, str] = Field(default_factory=dict)
