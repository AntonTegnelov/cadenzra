"""Score MIDI to performance MIDI: everything a performer adds and a score omits.

A pure transform, deliberately *not* behind a protocol: there is no vendor to
swap and no non-determinism to fake, so a protocol here would be ceremony
(docs/06, docs/08 principle 5).

The split it implements is the point (docs/02). The score domain ends at score
MIDI — quantized, mechanical, what the notation *says*, and what every
validator analyzes. This is where interpretation begins, and nothing downstream
of it is ever analyzed for correctness: verifying a composition against a
deliberate groove would turn every swung eighth into a rhythm error.

v1 realizes the dynamics curves fully, because the first piece's held-chord
crescendos are inaudible without them, and is identity for the rest. Swing,
per-voice timing and technique mappings fill in behind this same seam as needs
demonstrate — the seam is what was bought, not the features.
"""

import logging
from fractions import Fraction
from typing import Final

import mido

from cadenzra.model.interpretation import ControlChange, InterpretationParams, ProgramChange
from cadenzra.model.primitives.ids import SectionId, VoiceId
from cadenzra.model.structure import StructurePlan
from cadenzra.performance.curves import (
    EXPRESSION_CONTROLLER,
    CurvePoint,
    dynamics_plan_to_cc_events,
)
from cadenzra.verification.midi_analysis import voice_id_of_track

_log = logging.getLogger(__name__)

_WHOLE_NOTES_PER_BEAT: Final = Fraction(1, 4)


def interpret_performance(
    score_midi: mido.MidiFile,
    plan: StructurePlan,
    params: InterpretationParams,
) -> mido.MidiFile:
    """Score MIDI plus interpretation parameters, out comes performance MIDI.

    Pure given its inputs: the same score and the same parameters always
    produce the same performance, which is what makes runs reproducible and
    the transform testable against golden pairs (docs/09).
    """
    performance = mido.MidiFile(
        type=score_midi.type, ticks_per_beat=score_midi.ticks_per_beat
    )
    curve = _section_curve(plan, params)

    for track in score_midi.tracks:
        performance.tracks.append(_interpret_track(track, score_midi.ticks_per_beat, curve, params))

    return performance


def _section_curve(
    plan: StructurePlan, params: InterpretationParams
) -> list[CurvePoint]:
    """The whole piece's expression curve, in absolute whole notes.

    Each section's arc is computed against its own meter and bar count, then
    laid end to end — sections are the unit the plan describes dynamics in.
    """
    points: list[CurvePoint] = []
    elapsed = Fraction(0)
    for section in plan.sections:
        section_points = dynamics_plan_to_cc_events(
            section.dynamics,
            section.bars,
            section.meter,
            intensity=params.dynamics_curve_intensity,
        )
        points += [
            point.model_copy(update={"offset": point.offset + elapsed})
            for point in section_points
        ]
        elapsed += section.bars * section.meter.bar_length
    return points


def _interpret_track(
    track: mido.MidiTrack,
    ticks_per_beat: int,
    curve: list[CurvePoint],
    params: InterpretationParams,
) -> mido.MidiTrack:
    """One voice's track, with its expression curve woven in.

    The curve is inserted per track because expression is per channel — which
    is only possible because of the one-voice-one-channel invariant the
    assembler guarantees (docs/03).
    """
    channel = _channel_of(track)
    if channel is None or not curve:
        return _copied(track)

    voice_id = voice_id_of_track(track.name)
    events = _absolute_events(track)
    for point in curve:
        events.append(
            (
                _ticks(point.offset, ticks_per_beat),
                _order_of("control_change"),
                mido.Message(
                    "control_change",
                    channel=channel,
                    control=EXPRESSION_CONTROLLER,
                    value=point.value,
                ),
            )
        )
    events += _technique_events(voice_id, channel, params)

    events.sort(key=lambda item: (item[0], item[1]))
    return _to_track(track.name, events)


def _technique_events(
    voice_id: VoiceId, channel: int, params: InterpretationParams
) -> list[tuple[int, int, mido.Message]]:
    """Technique-to-timbre mappings, applied at the top of the track.

    v1 places them once rather than per span: a mapping that switches timbre
    mid-line needs the span positions, which is the next thing to build here
    when a piece actually asks for it.
    """
    events = []
    for technique, action in sorted(params.technique_mappings.items()):
        del technique
        if isinstance(action, ProgramChange):
            events.append(
                (
                    0,
                    _order_of("program_change"),
                    mido.Message(
                        "program_change", channel=channel, program=action.program
                    ),
                )
            )
        elif isinstance(action, ControlChange):
            events.append(
                (
                    0,
                    _order_of("control_change"),
                    mido.Message(
                        "control_change",
                        channel=channel,
                        control=action.controller,
                        value=action.value,
                    ),
                )
            )
    del voice_id
    return events


def _channel_of(track: mido.MidiTrack) -> int | None:
    for message in track:
        if not message.is_meta and message.type in ("note_on", "note_off"):
            return int(message.channel)
    return None


def _absolute_events(track: mido.MidiTrack) -> list[tuple[int, int, mido.Message]]:
    """A track's messages with absolute ticks, ready to merge and re-sort."""
    events = []
    tick = 0
    for message in track:
        tick += message.time
        events.append((tick, _order_of(message.type), message))
    return events


def _order_of(message_type: str) -> int:
    """Tie-break for events at the same tick.

    Expression must be set *before* the note it shapes, or the first instant of
    a phrase sounds at the previous dynamic. Note-offs precede note-ons so a
    repeated pitch retriggers cleanly.
    """
    return {
        "control_change": 0,
        "program_change": 0,
        "pitchwheel": 0,
        "note_off": 1,
        "note_on": 2,
    }.get(message_type, 0)


def _to_track(
    name: str, events: list[tuple[int, int, mido.Message]]
) -> mido.MidiTrack:
    """Rebuild a track from absolute-tick events, restoring delta times."""
    track = mido.MidiTrack()
    track.name = name
    previous = 0
    for tick, _, message in events:
        track.append(message.copy(time=tick - previous))
        previous = tick
    return track


def _copied(track: mido.MidiTrack) -> mido.MidiTrack:
    copy = mido.MidiTrack()
    copy.name = track.name
    for message in track:
        copy.append(message.copy())
    return copy


def _ticks(offset: Fraction, ticks_per_beat: int) -> int:
    return int(offset / _WHOLE_NOTES_PER_BEAT * ticks_per_beat)


def section_offsets(plan: StructurePlan) -> dict[SectionId, Fraction]:
    """Where each section begins, in absolute whole notes."""
    offsets = {}
    elapsed = Fraction(0)
    for section in plan.sections:
        offsets[section.section_id] = elapsed
        elapsed += section.bars * section.meter.bar_length
    return offsets
