"""`PieceSpec` — the user's intent, and the only input the pipeline takes."""

from typing import Literal, Self

from pydantic import BaseModel, model_validator

from cadenzra.model.primitives.ids import VoiceId
from cadenzra.model.primitives.meter import MeterSpec
from cadenzra.model.primitives.pitch import Pitch


class VoiceSpec(BaseModel, frozen=True):
    """One part in the ensemble.

    `range_low`/`range_high` are hard constraints: a note outside them is a
    validator failure, never a warning (docs/03).
    """

    voice_id: VoiceId
    kind: Literal["vocal", "instrument"]
    group: str | None = None
    range_low: Pitch
    range_high: Pitch
    midi_program: int
    lyrics: bool = False

    @model_validator(mode="after")
    def _check_range(self) -> Self:
        if self.range_low.cents > self.range_high.cents:
            raise ValueError(
                f"voice {self.voice_id!r} has range_low {self.range_low.to_scientific()} "
                f"above range_high {self.range_high.to_scientific()}"
            )
        if not 0 <= self.midi_program <= 127:
            raise ValueError(
                f"voice {self.voice_id!r} has midi_program {self.midi_program}, "
                "which is outside 0-127"
            )
        return self


class PieceSpec(BaseModel, frozen=True):
    """What to compose. Style arrives as free text and is interpreted once,
    into a `StylePack`, so no downstream node re-interprets it (docs/04)."""

    title: str
    style_prompt: str
    voices: list[VoiceSpec]
    meters_allowed: list[MeterSpec]
    key_center: str | None = None
    target_minutes: float
    tempo_bpm: int | None = None
    language: str | None = None

    @model_validator(mode="after")
    def _check_piece(self) -> Self:
        if not self.voices:
            raise ValueError("a piece needs at least one voice")
        seen = [voice.voice_id for voice in self.voices]
        duplicates = {name for name in seen if seen.count(name) > 1}
        if duplicates:
            raise ValueError(f"duplicate voice ids: {sorted(duplicates)}")
        if not self.meters_allowed:
            raise ValueError("a piece needs at least one allowed meter")
        if self.target_minutes <= 0:
            raise ValueError(f"target_minutes must be positive, got {self.target_minutes}")
        return self

    @property
    def voices_by_id(self) -> dict[VoiceId, VoiceSpec]:
        return {voice.voice_id: voice for voice in self.voices}

    @property
    def groups(self) -> set[str]:
        return {voice.group for voice in self.voices if voice.group is not None}

    @property
    def has_lyrics(self) -> bool:
        return any(voice.lyrics for voice in self.voices)
