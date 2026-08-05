"""`PipelineState` — every layer's artifacts plus the open feedback.

Nodes are pure with respect to this: each takes the state, returns the fields
it changed, and never mutates a shared structure in place (docs/02).

**One deviation from the docs/02 sketch.** It types `voices` as
`dict[tuple[SectionId, VoiceId], VoicePart]`. Tuple keys do not survive a JSON
round-trip — pydantic writes `{"a,b": ...}` and cannot read it back — and
docs/07 requires the final state to be dumped as JSON as a complete debugging
record. The key is therefore a flat string built by `voice_key`; each
`VoicePart` still carries its own `section_id`/`voice_id`, so the key is pure
bookkeeping and nothing is lost. It also keeps the fan-out merge a plain dict
union, which matters when the (section x voice) fan-out writes concurrently.
"""

from pydantic import BaseModel, Field

from cadenzra.model.artifacts import AssembledScore, AssembledSection, RenderedArtifacts
from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.harmony import HarmonicSkeleton
from cadenzra.model.interpretation import InterpretationParams
from cadenzra.model.motif import MotifLibrary
from cadenzra.model.primitives.ids import SectionId, VoiceId
from cadenzra.model.spec import PieceSpec
from cadenzra.model.structure import StructurePlan
from cadenzra.model.style import StylePack
from cadenzra.model.voice import VoicePart

_KEY_SEPARATOR = "::"


def voice_key(section_id: SectionId, voice_id: VoiceId) -> str:
    """The `state.voices` key for one (section, voice) pair."""
    return f"{section_id}{_KEY_SEPARATOR}{voice_id}"


def attempt_key(level: str, section_id: SectionId | None, voice_id: VoiceId | None) -> str:
    """The `state.attempts` key identifying one generate/validate loop.

    Budgets are per loop identity — `voice:altoB` and `voice:sopranoB` spend
    separately — so one stubborn alto line cannot starve the rest of the piece
    (docs/02).
    """
    parts = [level, *(part for part in (section_id, voice_id) if part is not None)]
    return ":".join(parts)


class PipelineState(BaseModel):
    """The graph's single state object, append-mostly.

    `interpretation` lives here, rather than inside the interpreter, so the
    critique loop can turn its knobs — that is what makes "sounds stiff" a
    parameter change instead of a regeneration (docs/02).
    """

    spec: PieceSpec
    style: StylePack | None = None
    structure: StructurePlan | None = None
    motifs: MotifLibrary | None = None
    harmony: dict[SectionId, HarmonicSkeleton] = Field(default_factory=dict)
    voices: dict[str, VoicePart] = Field(default_factory=dict)
    sections: dict[SectionId, AssembledSection] = Field(default_factory=dict)
    score: AssembledScore | None = None
    interpretation: InterpretationParams | None = None
    artifacts: RenderedArtifacts | None = None
    feedback: list[FeedbackItem] = Field(default_factory=list)
    attempts: dict[str, int] = Field(default_factory=dict)

    def voice_part(self, section_id: SectionId, voice_id: VoiceId) -> VoicePart:
        """Direct lookup. A missing key after validation is a broken invariant,
        so this raises rather than returning None (docs/08, principle 4)."""
        return self.voices[voice_key(section_id, voice_id)]

    def feedback_for(
        self, level: str, section_id: SectionId | None = None, voice_id: VoiceId | None = None
    ) -> list[FeedbackItem]:
        """Open feedback targeting one unit — what a regeneration prompt reads."""
        return [
            item
            for item in self.feedback
            if item.level == level
            and (section_id is None or item.section_id == section_id)
            and (voice_id is None or item.voice_id == voice_id)
        ]
