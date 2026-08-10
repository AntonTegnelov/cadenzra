"""`FeedbackItem` — the universal failure currency.

Every validator failure and critic observation is this one shape, because
`level` plus the ids is what routes work back to the smallest unit that can fix
it (docs/05). `location` is internal (an offset); `message` always speaks
bar/beat, because its real consumer is a regeneration prompt — feedback is part
of the LLM surface and follows the surface rules (docs/08, principle 2).

The identity fields (`kind`, `voices`, `span`) exist because the message is
prose and prose is a bad key: the cost audit had to match verbatim strings to
learn which violations survived three repair sweeps. `fingerprint()` names what
a violation *is* — its kind, place and participants — so "is the loop
converging" becomes a set computation instead of a diff of wordings.
"""

from fractions import Fraction
from hashlib import sha1
from typing import Literal

from pydantic import BaseModel

from cadenzra.model.primitives.ids import SectionId, VoiceId

type FeedbackLevel = Literal[
    "structure",
    "motif",
    "harmony",
    "lyric",
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

    # Structured identity. `voices` names every voice a relationship involves
    # (`voice_id` stays the routed target); `span` is the offsets of a
    # collapsed run; `routing` records why the target was chosen
    # ("only-free-voice" | "both-free" | "unfixable").
    kind: str | None = None
    voices: tuple[VoiceId, ...] = ()
    span: tuple[Fraction, Fraction] | None = None
    routing: str | None = None

    def fingerprint(self) -> str:
        """A short stable id for *what* is wrong, independent of wording.

        The routed voice is deliberately excluded: the same clash handed to the
        other voice of a pair is still one fault, and counting it twice would
        make every both-free repair look like a growing problem.
        """
        place = self.span[0] if self.span is not None else self.location
        participants = self.voices or ((self.voice_id,) if self.voice_id else ())
        key = "|".join(
            (
                self.kind or self.source,
                self.section_id or "",
                ",".join(sorted(participants)),
                str(place) if place is not None else "",
            )
        )
        return sha1(key.encode()).hexdigest()[:8]
