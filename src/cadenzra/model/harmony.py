"""`HarmonicSkeleton` — the chord ground each section's voices are written over.

Events are stored in internal coordinates (absolute `Fraction` offsets). The
schema an LLM fills speaks bar/beat/chord-symbol; `llm/parsers/` converts
(docs/03). Gaplessness and exact fill are checked with exact arithmetic before
any notation exists — the cheapest place to catch a mis-summed section.
"""

from fractions import Fraction
from typing import Self

from pydantic import BaseModel, model_validator

from cadenzra.model.primitives.ids import SectionId


class HarmonicEvent(BaseModel, frozen=True):
    offset: Fraction
    duration: Fraction
    chord: str

    @model_validator(mode="after")
    def _check_event(self) -> Self:
        if self.offset < 0:
            raise ValueError(f"harmonic event at negative offset {self.offset}")
        if self.duration <= 0:
            raise ValueError(
                f"harmonic event {self.chord!r} has non-positive duration {self.duration}"
            )
        return self

    @property
    def end(self) -> Fraction:
        return self.offset + self.duration


class HarmonicSkeleton(BaseModel, frozen=True):
    """One section's progression. Ordering and gaplessness are the validator's
    job (`verification/harmony.py`), not this model's — the model holds even
    the malformed skeleton an LLM produced, so feedback can describe it."""

    section_id: SectionId
    events: list[HarmonicEvent]

    @property
    def span(self) -> Fraction:
        """Total length covered, assuming the events are gapless."""
        return max((event.end for event in self.events), default=Fraction(0))

    def chord_at(self, offset: Fraction) -> str | None:
        """The chord sounding at an offset, or None if nothing covers it."""
        for event in self.events:
            if event.offset <= offset < event.end:
                return event.chord
        return None
