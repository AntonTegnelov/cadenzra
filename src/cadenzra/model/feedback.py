"""`FeedbackItem` — the universal failure currency.

Every validator failure and critic observation is this one shape, because
`level` plus the ids is what routes work back to the smallest unit that can fix
it (docs/05). `location` is internal (an offset); `message` always speaks
bar/beat, because its real consumer is a regeneration prompt — feedback is part
of the LLM surface and follows the surface rules (docs/08, principle 2).
"""

from fractions import Fraction
from typing import Literal

from pydantic import BaseModel

from cadenzra.model.primitives.ids import SectionId, VoiceId

type FeedbackLevel = Literal[
    "structure",
    "motif",
    "harmony",
    "voice",
    "section",
    "score",
    "interpretation",
    "render",
]


class FeedbackItem(BaseModel, frozen=True):
    source: str
    level: FeedbackLevel
    section_id: SectionId | None = None
    voice_id: VoiceId | None = None
    location: Fraction | None = None
    message: str
    evidence: str | None = None
