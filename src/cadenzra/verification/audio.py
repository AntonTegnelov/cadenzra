"""Checking the rendered audio against the dynamics the plan asked for.

This exists because of an empirical result, not a hunch. The audio critic was
asked whether a piece's dynamic arc landed, with the intended arc included in
its brief — and it confidently reported hearing a "powerful ff climax" in a
performance rendered at one constant velocity with no expression at all. Given
the *same* audio and a brief with the intentions removed, it correctly said
nothing about dynamics. Telling a listener what to expect makes it report
hearing that.

So the question moves to where it was always decidable. Whether the
interpretation stage put a shape into the performance is a fact about the
controller curve, and docs/05's own rule is to prefer decidable checks over
judgment. The critic keeps the questions only ears can answer; this answers the
one a number can.
"""

import math
import wave
from array import array
from fractions import Fraction
from pathlib import Path
from typing import Final

import mido

from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.structure import StructurePlan
from cadenzra.performance.curves import (
    DYNAMIC_LEVELS,
    EXPRESSION_CONTROLLER,
    level_of,
)

SOURCE: Final = "verify_audio"

# How many slices the envelope is measured in. Fine enough to see a swell
# inside one section, coarse enough not to track individual note attacks.
_SLICES: Final = 32

# A rendered file this quiet throughout is silence, not a performance.
_MIN_AUDIBLE_RMS: Final = 1.0

# How much of the planned controller range the performance must actually carry.
# Not 100%: the curve is scaled by `dynamics_curve_intensity`, and a style that
# dials expression down is making a choice, not failing. Well under half the
# planned range means the curve is essentially absent.
_MIN_REALIZED_SHARE: Final = 0.4

# Below this spread the plan is not asking for an arc, so there is nothing to
# check. Expressed in controller units.
_FLAT_PLAN: Final = 20


def rms_envelope(audio: Path, *, slices: int = _SLICES) -> list[float]:
    """The waveform's loudness over time, as `slices` equal windows."""
    with wave.open(str(audio)) as handle:
        channels = handle.getnchannels()
        samples = array("h")
        samples.frombytes(handle.readframes(handle.getnframes()))

    mono = samples[0::channels]
    if not mono:
        return []
    width = max(1, len(mono) // slices)
    return [
        math.sqrt(
            sum(float(s) * s for s in mono[index * width : (index + 1) * width]) / width
        )
        for index in range(slices)
        if index * width < len(mono)
    ]


def planned_spread(plan: StructurePlan) -> int:
    """How much dynamic range the plan asks for, in controller units."""
    levels = []
    for section in plan.sections:
        levels.append(level_of(section.dynamics.start))
        levels += [level_of(target.level) for target in section.dynamics.targets]
    if not levels:
        return 0
    return max(levels) - min(levels)


def validate_audio_dynamics(
    audio: Path, performance_midi: Path, plan: StructurePlan
) -> list[FeedbackItem]:
    """Whether the performance actually carries the shape the plan asked for.

    The check reads the *performance MIDI*, not the waveform. Waveform loudness
    is a poor instrument here: a synthesizer's note attacks and releases alone
    produce a three-to-one swing, which is the same order as a real but modest
    crescendo, so a threshold over it either misses the failure or invents one.
    The controller curve is exact and says the thing that matters directly —
    did the interpretation stage put a shape into this performance or not.

    The waveform is still checked, for the one thing it answers best: whether
    anything came out at all.
    """
    return [
        *_check_audible(audio),
        *_check_expression(performance_midi, plan),
    ]


def _check_audible(audio: Path) -> list[FeedbackItem]:
    envelope = rms_envelope(audio)
    if envelope and max(envelope) >= _MIN_AUDIBLE_RMS:
        return []
    return [_item("the rendered audio is silent")]


def _check_expression(
    performance_midi: Path, plan: StructurePlan
) -> list[FeedbackItem]:
    """The planned dynamic range, against the one the performance carries."""
    planned = planned_spread(plan)
    if planned < _FLAT_PLAN:
        return []

    values = _expression_values(performance_midi)
    realized = max(values) - min(values) if values else 0
    if realized >= planned * _MIN_REALIZED_SHARE:
        return []

    return [
        _item(
            f"the plan asks for a dynamic range from "
            f"{_nearest_dynamic(min(_levels(plan)))} to "
            f"{_nearest_dynamic(max(_levels(plan)))}, but the performance carries "
            f"almost none of it ({realized} of {planned} controller steps); the "
            "held notes will not swell"
        )
    ]


def _expression_values(performance_midi: Path) -> list[int]:
    return [
        int(message.value)
        for track in mido.MidiFile(performance_midi).tracks
        for message in track
        if message.type == "control_change"
        and message.control == EXPRESSION_CONTROLLER
    ]


def _levels(plan: StructurePlan) -> list[int]:
    levels = []
    for section in plan.sections:
        levels.append(level_of(section.dynamics.start))
        levels += [level_of(target.level) for target in section.dynamics.targets]
    return levels or [DYNAMIC_LEVELS["mf"]]


def _nearest_dynamic(value: int) -> str:
    return min(DYNAMIC_LEVELS, key=lambda name: abs(DYNAMIC_LEVELS[name] - value))


def _item(message: str) -> FeedbackItem:
    return FeedbackItem(
        source=SOURCE,
        level="interpretation",
        location=Fraction(0),
        message=message,
    )
