"""`InterpretationParams` — the performance domain's knobs.

These live in pipeline state rather than inside the interpreter precisely so
the critique loop can turn them: "sounds rushed" becomes a parameter change
instead of a regeneration, which is most of what the score/performance split
buys (docs/02, docs/05).
"""

from typing import Literal

from pydantic import BaseModel, Field

from cadenzra.model.primitives.ids import SectionId, VoiceId


class ProgramChange(BaseModel, frozen=True):
    """Switch a voice's timbre — the coarse technique mapping."""

    kind: Literal["program"] = "program"
    program: int


class ControlChange(BaseModel, frozen=True):
    """Set a controller on a voice's channel."""

    kind: Literal["control"] = "control"
    controller: int
    value: int


type MidiAction = ProgramChange | ControlChange


class InterpretationParams(BaseModel, frozen=True):
    """How to perform what the score says.

    v1 realizes `dynamics_curve_intensity` (held-chord crescendos are inaudible
    without it) and leaves the rest as identity — the seam is the point
    (docs/03).
    """

    swing: dict[SectionId, float] = Field(default_factory=dict)
    voice_offset_ms: dict[VoiceId, float] = Field(default_factory=dict)
    dynamics_curve_intensity: float = 1.0
    technique_mappings: dict[str, MidiAction] = Field(default_factory=dict)
