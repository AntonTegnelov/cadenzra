"""`VoicePart` — one voice's notation for one section.

Techniques appear twice by design: as standard markup inside `lily_music` for
the engraved score, and as this structured list for the audio path. The
structured copy drives interpretation; cross-checking the two would be a
LilyPond parser through the back door, guarding a cosmetic divergence, so it is
deliberately left to the critic (docs/03, docs/08 principle 3).
"""

from typing import Final, Self

from pydantic import BaseModel, Field, model_validator

from cadenzra.model.primitives.ids import SectionId, VoiceId

TECHNIQUE_VOCABULARY: Final[frozenset[str]] = frozenset(
    {
        # bowed strings
        "sul pont.",
        "sul tasto",
        "pizz.",
        "arco",
        "con sord.",
        "senza sord.",
        "tremolo",
        "harmonic",
        # voice
        "whispered",
        "spoken",
        "hummed",
        "closed mouth",
        "falsetto",
        "vocal fry",
        # general
        "gliss",
        "portamento",
        "flutter",
        "accent",
    }
)


class TechniqueSpan(BaseModel, frozen=True):
    """A technique over a bar range; `to_bar` None marks a point event."""

    technique: str
    from_bar: int
    to_bar: int | None = None

    @model_validator(mode="after")
    def _check_span(self) -> Self:
        if self.technique not in TECHNIQUE_VOCABULARY:
            raise ValueError(
                f"{self.technique!r} is not in the technique vocabulary; "
                f"known techniques are {sorted(TECHNIQUE_VOCABULARY)}"
            )
        if self.from_bar < 1:
            raise ValueError(f"technique spans start at bar 1 or later, got {self.from_bar}")
        if self.to_bar is not None and self.to_bar < self.from_bar:
            raise ValueError(
                f"technique {self.technique!r} ends at bar {self.to_bar}, "
                f"before it starts at bar {self.from_bar}"
            )
        return self


class VoicePart(BaseModel, frozen=True):
    """One (section, voice) fragment under the generator contract (docs/03).

    `lily_music` is a pure music expression: absolute pitch, explicit
    durations, a bar check at every barline, no structural commands. None of
    that is enforced here — it is enforced by the compiler and the analysis
    path, at the layer that can actually check it.
    """

    section_id: SectionId
    voice_id: VoiceId
    lily_music: str
    lily_lyrics: str | None = None
    techniques: list[TechniqueSpan] = Field(default_factory=list)
