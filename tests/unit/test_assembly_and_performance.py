"""Contracts for assembly and the interpretation transform.

Both are pure, so both are tested as values in, values out. The two properties
that matter most: the assembler declares the one-voice-one-channel invariant
every later subsystem depends on, and the interpretation transform realizes a
dynamics plan as a curve that actually reaches the levels the plan asked for.
"""

from fractions import Fraction

import mido
import pytest

from cadenzra.model.interpretation import InterpretationParams
from cadenzra.model.primitives.meter import simple_meter
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.spec import PieceSpec, VoiceSpec
from cadenzra.model.structure import DynamicsPlan, DynTarget, SectionPlan, StructurePlan
from cadenzra.model.voice import VoicePart
from cadenzra.notation.assemble import assemble_score, assemble_section, variable_name
from cadenzra.notation.instruments import instrument_name
from cadenzra.performance.curves import (
    DYNAMIC_LEVELS,
    EXPRESSION_CONTROLLER,
    dynamics_plan_to_cc_events,
    level_of,
)
from cadenzra.performance.interpret import interpret_performance

SEVEN_EIGHT = simple_meter(7, 8, [2, 2, 3])
FOUR_FOUR = simple_meter(4, 4)
TICKS = 384

SOPRANO = VoiceSpec(
    voice_id="soprano",
    kind="vocal",
    range_low=Pitch(step="C", octave=4),
    range_high=Pitch(step="A", octave=5),
    midi_program=52,
    lyrics=True,
)
BASS = VoiceSpec(
    voice_id="bass",
    kind="vocal",
    range_low=Pitch(step="E", octave=2),
    range_high=Pitch(step="C", octave=4),
    midi_program=52,
)

SPEC = PieceSpec(
    title="Test Piece",
    style_prompt="s",
    voices=[SOPRANO, BASS],
    meters_allowed=[SEVEN_EIGHT],
    target_minutes=1.0,
)

SECTION = SectionPlan(
    section_id="A",
    bars=2,
    meter=SEVEN_EIGHT,
    key="d phrygian",
    tempo_bpm=96,
    texture="homophonic",
    dynamics=DynamicsPlan(start="pp", targets=[DynTarget(bar=2, level="ff")]),
    active_voices=["soprano", "bass"],
)

PARTS = {
    "soprano": VoicePart(
        section_id="A",
        voice_id="soprano",
        lily_music="d''8 d'' e'' e'' f''4. |\ne''8 e'' d'' d'' c''4. |",
        lily_lyrics="\\lyricmode { Sing the mea -- sure now hold the qui -- et line }",
    ),
    "bass": VoicePart(
        section_id="A", voice_id="bass", lily_music="d8 d d d d4. |\nc8 c c c c4. |"
    ),
}


def test_a_section_wraps_each_fragment_in_the_structure_it_omits() -> None:
    section = assemble_section(SECTION, PARTS, SPEC)

    assert variable_name("A", "soprano") in section.lily_source
    assert "\\time #'(2 2 3) 7/8" in section.lily_source
    assert "\\tempo 4 = 96" in section.lily_source
    assert "\\key d \\phrygian" in section.lily_source
    assert section.voice_order == ["soprano", "bass"]


def test_fragments_are_carried_through_verbatim() -> None:
    section = assemble_section(SECTION, PARTS, SPEC)

    assert "d''8 d'' e'' e'' f''4. |" in section.lily_source


def test_the_score_declares_the_channel_invariant_it_depends_on() -> None:
    """Wrapping each staff in a named Voice makes the MIDI track carry the
    voice id, and the explicit mapping makes the invariant declared rather than
    inherited from a default (docs/03, M0 empirical answer)."""
    sections = {"A": assemble_section(SECTION, PARTS, SPEC)}

    score = assemble_score(StructurePlan(sections=[SECTION]), sections, SPEC)

    assert 'midiChannelMapping = #\'staff' in score.lily_source
    assert '\\new Voice = "soprano"' in score.lily_source
    assert '\\new Voice = "bass"' in score.lily_source


def test_each_voice_gets_its_general_midi_instrument_by_name() -> None:
    sections = {"A": assemble_section(SECTION, PARTS, SPEC)}

    score = assemble_score(StructurePlan(sections=[SECTION]), sections, SPEC)

    assert f'midiInstrument = "{instrument_name(52)}"' in score.lily_source
    assert instrument_name(52) == "choir aahs"


def test_sections_appear_in_plan_order() -> None:
    second = SECTION.model_copy(update={"section_id": "B"})
    parts_b = {
        voice_id: part.model_copy(update={"section_id": "B"})
        for voice_id, part in PARTS.items()
    }
    sections = {
        "A": assemble_section(SECTION, PARTS, SPEC),
        "B": assemble_section(second, parts_b, SPEC),
    }

    score = assemble_score(StructurePlan(sections=[SECTION, second]), sections, SPEC)

    soprano_line = next(
        line for line in score.lily_source.split("\n") if '\\new Voice = "soprano"' in line
    )
    assert soprano_line.index(variable_name("A", "soprano")) < soprano_line.index(
        variable_name("B", "soprano")
    )


def test_lyrics_are_attached_only_to_the_voice_that_sings_them() -> None:
    sections = {"A": assemble_section(SECTION, PARTS, SPEC)}

    score = assemble_score(StructurePlan(sections=[SECTION]), sections, SPEC)

    assert '\\lyricsto "soprano"' in score.lily_source
    assert '\\lyricsto "bass"' not in score.lily_source


def test_an_unrecognized_mode_omits_the_key_rather_than_inventing_one() -> None:
    """Guessing a key signature would silently change what the score says."""
    section = assemble_section(
        SECTION.model_copy(update={"key": "octatonic on d"}), PARTS, SPEC
    )

    assert "\\key" not in section.lily_source


PLAN = StructurePlan(sections=[SECTION])


def test_a_crescendo_reaches_the_level_the_plan_asked_for() -> None:
    points = dynamics_plan_to_cc_events(SECTION.dynamics, 2, SEVEN_EIGHT)

    assert points[0].value == DYNAMIC_LEVELS["pp"]
    assert max(point.value for point in points) == DYNAMIC_LEVELS["ff"]


def test_a_crescendo_is_a_ramp_not_a_step() -> None:
    """A single jump at the target bar is not a crescendo — the whole point is
    that the swell is continuous across the held notes (docs/02)."""
    points = dynamics_plan_to_cc_events(SECTION.dynamics, 2, SEVEN_EIGHT)

    assert len(points) > 8
    values = [point.value for point in points]
    assert values == sorted(values)


def test_a_flat_plan_produces_a_single_setting() -> None:
    points = dynamics_plan_to_cc_events(DynamicsPlan(start="mf"), 2, SEVEN_EIGHT)

    assert len(points) == 1
    assert points[0].value == DYNAMIC_LEVELS["mf"]


def test_intensity_flattens_the_arc_toward_the_middle() -> None:
    """Turning intensity down must not just make everything quieter — "too
    extreme" is a complaint about range, not about volume."""
    full = dynamics_plan_to_cc_events(SECTION.dynamics, 2, SEVEN_EIGHT, intensity=1.0)
    flat = dynamics_plan_to_cc_events(SECTION.dynamics, 2, SEVEN_EIGHT, intensity=0.5)

    full_range = max(p.value for p in full) - min(p.value for p in full)
    flat_range = max(p.value for p in flat) - min(p.value for p in flat)
    assert flat_range < full_range
    assert min(p.value for p in flat) > min(p.value for p in full)


def test_a_zero_intensity_arc_is_flat_at_the_middle() -> None:
    points = dynamics_plan_to_cc_events(SECTION.dynamics, 2, SEVEN_EIGHT, intensity=0.0)

    assert {point.value for point in points} == {DYNAMIC_LEVELS["mf"]}


@pytest.mark.parametrize("name", sorted(DYNAMIC_LEVELS))
def test_every_italian_dynamic_maps_to_a_controller_value(name: str) -> None:
    assert 0 <= level_of(name) <= 127


def test_an_unknown_dynamic_falls_back_to_the_middle() -> None:
    assert level_of("sfzzz") == DYNAMIC_LEVELS["mf"]


def _score_midi() -> mido.MidiFile:
    midi = mido.MidiFile(type=1, ticks_per_beat=TICKS)
    for channel, name in enumerate(("staff:soprano", "staff:bass")):
        track = mido.MidiTrack()
        track.name = name
        midi.tracks.append(track)
        track.append(mido.Message("note_on", channel=channel, note=60, velocity=90, time=0))
        track.append(
            mido.Message("note_off", channel=channel, note=60, velocity=0, time=TICKS * 7)
        )
    return midi


def test_the_performance_carries_expression_the_score_midi_lacks() -> None:
    score = _score_midi()

    performance = interpret_performance(score, PLAN, InterpretationParams())

    assert not _expression_events(score)
    assert _expression_events(performance)


def test_expression_is_written_per_voice_on_its_own_channel() -> None:
    """Per-channel dynamics exist only because of the one-voice-one-channel
    invariant; writing them all on one channel would shape the wrong voices."""
    performance = interpret_performance(_score_midi(), PLAN, InterpretationParams())

    for track in performance.tracks:
        channels = {m.channel for m in track if not m.is_meta}
        assert len(channels) == 1


def test_expression_is_set_before_the_note_it_shapes() -> None:
    """Otherwise the first instant of a phrase sounds at the previous dynamic."""
    performance = interpret_performance(_score_midi(), PLAN, InterpretationParams())

    for track in performance.tracks:
        types = [m.type for m in track if not m.is_meta]
        if "note_on" in types and "control_change" in types:
            assert types.index("control_change") < types.index("note_on")


def test_the_transform_is_pure_and_leaves_the_score_untouched() -> None:
    score = _score_midi()
    before = [[m.bytes() for m in track] for track in score.tracks]

    interpret_performance(score, PLAN, InterpretationParams())

    assert [[m.bytes() for m in track] for track in score.tracks] == before


def test_the_same_inputs_always_produce_the_same_performance() -> None:
    """Reproducible runs stay reproducible (docs/06)."""
    first = interpret_performance(_score_midi(), PLAN, InterpretationParams())
    second = interpret_performance(_score_midi(), PLAN, InterpretationParams())

    assert _dump(first) == _dump(second)


def test_notes_survive_interpretation_unchanged() -> None:
    """Interpretation shapes a performance; it never rewrites the music."""
    score = _score_midi()

    performance = interpret_performance(score, PLAN, InterpretationParams())

    assert _notes(performance) == _notes(score)


def _expression_events(midi: mido.MidiFile) -> list[mido.Message]:
    return [
        message
        for track in midi.tracks
        for message in track
        if message.type == "control_change" and message.control == EXPRESSION_CONTROLLER
    ]


def _notes(midi: mido.MidiFile) -> list[tuple[int, int]]:
    return [
        (message.note, message.channel)
        for track in midi.tracks
        for message in track
        if message.type == "note_on"
    ]


def _dump(midi: mido.MidiFile) -> list[list[bytes]]:
    return [[bytes(message.bytes()) for message in track] for track in midi.tracks]


def test_sections_lay_their_curves_end_to_end() -> None:
    """Each section's arc is computed in its own meter, then placed in sequence."""
    second = SECTION.model_copy(
        update={"section_id": "B", "dynamics": DynamicsPlan(start="p")}
    )
    plan = StructurePlan(sections=[SECTION, second])

    performance = interpret_performance(_score_midi(), plan, InterpretationParams())

    values = [message.value for message in _expression_events(performance)]
    assert DYNAMIC_LEVELS["pp"] in values
    assert DYNAMIC_LEVELS["ff"] in values
    assert DYNAMIC_LEVELS["p"] in values


def test_the_curve_reaches_its_target_exactly_at_the_target_bar() -> None:
    """It need not emit anything after that: a controller holds its value, so
    a repeated setting at the section end would be noise, not shape."""
    points = dynamics_plan_to_cc_events(
        DynamicsPlan(start="pp", targets=[DynTarget(bar=4, level="ff")]), 4, FOUR_FOUR
    )

    assert points[-1].offset == Fraction(3)
    assert points[-1].value == DYNAMIC_LEVELS["ff"]
    assert all(point.value < DYNAMIC_LEVELS["ff"] for point in points[:-1])


def test_a_voice_silent_in_a_section_rests_through_it() -> None:
    """Skipping the voice instead makes its staff shorter than the others, and
    from the next section onward its barlines sit somewhere different — a score
    that will not compile even though every part compiled on its own. This was
    a real failure on the commission piece, where the opening section had one
    voice and the rest had four."""
    soprano_only = {"soprano": PARTS["soprano"]}

    section = assemble_section(SECTION, soprano_only, SPEC)

    assert section.voice_order == ["soprano"], "only the soprano actually sings"
    assert variable_name("A", "bass") in section.lily_source
    assert "R1*7/8*2" in section.lily_source


def test_every_staff_spans_every_section() -> None:
    quiet_open = SECTION.model_copy(update={"section_id": "Intro"})
    full = SECTION.model_copy(update={"section_id": "B"})
    parts_b = {
        voice_id: part.model_copy(update={"section_id": "B"})
        for voice_id, part in PARTS.items()
    }
    sections = {
        "Intro": assemble_section(quiet_open, {"soprano": PARTS["soprano"]}, SPEC),
        "B": assemble_section(full, parts_b, SPEC),
    }

    score = assemble_score(StructurePlan(sections=[quiet_open, full]), sections, SPEC)

    bass_line = next(
        line for line in score.lily_source.split("\n") if '\\new Voice = "bass"' in line
    )
    assert variable_name("Intro", "bass") in bass_line
    assert variable_name("B", "bass") in bass_line


@pytest.mark.parametrize(
    ("meter", "bars", "expected"),
    [
        (SEVEN_EIGHT, 16, "R1*7/8*16"),
        (FOUR_FOUR, 4, "R1*1/1*4"),
    ],
)
def test_a_silence_is_exactly_as_long_as_its_section(
    meter: object, bars: int, expected: str
) -> None:
    """Spelling the bar length out is what makes this work for any meter, not
    only those a whole note divides evenly."""
    from cadenzra.notation.assemble import multi_measure_rest

    section = SECTION.model_copy(update={"meter": meter, "bars": bars})

    assert multi_measure_rest(section) == expected
