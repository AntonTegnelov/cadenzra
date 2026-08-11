"""The grid must fit the subjects it harmonizes — checked at plan time.

The double-fugue's three immortal violations were the subject's E♭ against the
plan's own G-family chords, detected three layers downstream where no voice
could fix them. This check runs inside the harmony convergence loop, where the
grid — the side that is free to move — is the thing being regenerated.
"""

from fractions import Fraction

from cadenzra.model.harmony import HarmonicEvent, HarmonicSkeleton
from cadenzra.model.primitives.meter import simple_meter
from cadenzra.model.structure import DynamicsPlan, MaterialEntry, SectionPlan
from cadenzra.verification.harmony import check_entries_against_grid
from cadenzra.verification.midi_analysis import NoteEvent

FOUR_FOUR = simple_meter(4, 4)


def _section(*entries: MaterialEntry) -> SectionPlan:
    return SectionPlan(
        section_id="Exposition1",
        bars=4,
        meter=FOUR_FOUR,
        key="c minor",
        tempo_bpm=90,
        texture="imitative",
        dynamics=DynamicsPlan(start="mf"),
        active_voices=["cello", "viola"],
        material=list(entries),
    )


def _notes(pitches: list[int]) -> list[NoteEvent]:
    return [
        NoteEvent(
            midi_pitch=pitch,
            onset=Fraction(index, 4),
            duration=Fraction(1, 4),
            velocity=90,
            channel=0,
        )
        for index, pitch in enumerate(pitches)
    ]


# The autopsy's subject shape: Eb (63) sustained on beat 3 of bar 1.
SUBJECT = _notes([60, 55, 63, 62])


def _skeleton(*chords: str) -> HarmonicSkeleton:
    return HarmonicSkeleton(
        section_id="Exposition1",
        events=[
            HarmonicEvent(offset=Fraction(index, 4), duration=Fraction(1, 4), chord=chord)
            for index, chord in enumerate(chords)
        ],
    )


ENTRY = MaterialEntry(motif_id="subject1", voice_id="cello", bar=1, relation="exact")


def test_a_grid_contradicting_the_subject_is_caught_at_plan_time() -> None:
    """G7 under the subject's E♭: the exact contradiction that survived three
    repair sweeps downstream. Here it costs one harmony regeneration."""
    feedback = check_entries_against_grid(
        _skeleton("Cm", "Cm", "G7", "Cm"),
        _section(ENTRY),
        {"subject1": SUBJECT},
    )

    assert len(feedback) == 1
    item = feedback[0]
    assert item.level == "harmony", "the grid is the side that regenerates"
    assert "Eb4" in item.message and "ees'" in item.message
    assert "G7" in item.message
    assert "cannot change" in item.message
    assert item.kind == "entry_vs_grid"


def test_a_grid_that_fits_the_subject_passes() -> None:
    assert (
        check_entries_against_grid(
            _skeleton("Cm", "Cm", "Cm", "Cm"),
            _section(ENTRY),
            {"subject1": SUBJECT},
        )
        == []
    )


def test_a_transposed_entry_is_checked_at_its_sounding_pitch() -> None:
    """The P5-up answer moves the clash: Eb+7 = Bb, fine over G-anything minor
    but biting over an A major chord."""
    entry = MaterialEntry(motif_id="subject1", voice_id="viola", bar=1, relation="P5 up")

    fits = check_entries_against_grid(
        _skeleton("Gm", "Gm", "Gm", "Gm"), _section(entry), {"subject1": SUBJECT}
    )
    clashes = check_entries_against_grid(
        _skeleton("Gm", "Gm", "A", "Gm"), _section(entry), {"subject1": SUBJECT}
    )

    assert fits == []
    assert len(clashes) == 1


def test_a_tonal_answer_is_pinned_at_the_literal_fifth() -> None:
    """The prescription hands a tonal answer over as the literal real answer
    — the subject a fifth up — so the grid must fit that realization. When
    tonal answers were skipped here, the double-fugue's violin1 copied its
    prescribed whole-note answer perfectly and met a chord the plan-time
    check had never tested, after the section's one regrid was spent."""
    entry = MaterialEntry(
        motif_id="subject1", voice_id="viola", bar=1, relation="tonal answer"
    )

    fits = check_entries_against_grid(
        _skeleton("Gm", "Gm", "Gm", "Gm"), _section(entry), {"subject1": SUBJECT}
    )
    clashes = check_entries_against_grid(
        _skeleton("Gm", "Gm", "A", "Gm"), _section(entry), {"subject1": SUBJECT}
    )

    assert fits == []
    assert len(clashes) == 1, "Eb+7 = Bb bites over A major, exactly like 'P5 up'"


def test_a_chord_slot_reports_its_whole_requirement_set_with_an_example() -> None:
    """Two simultaneous subjects pinned A and Ab through one chord slot, and
    each complaint named one note — the model satisfied each by breaking the
    other, six grids running. One failing slot is one item naming every note
    the chord must contain, and the checker searches its own vocabulary for
    a chord that does — the answer, not the puzzle."""
    upper = MaterialEntry(
        motif_id="subject1", voice_id="viola", bar=1, relation="exact"
    )
    lower = MaterialEntry(
        motif_id="subject2", voice_id="cello", bar=1, relation="exact"
    )
    # Eb sustained in one subject against E in the other: only a #9 colour
    # holds both, and no complaint that names one note at a time can say so.
    e_natural = [
        NoteEvent(
            midi_pitch=64,
            onset=Fraction(0),
            duration=Fraction(1, 2),
            velocity=90,
            channel=0,
        )
    ]
    e_flat = [
        NoteEvent(
            midi_pitch=63,
            onset=Fraction(0),
            duration=Fraction(1, 2),
            velocity=90,
            channel=0,
        )
    ]
    skeleton = HarmonicSkeleton(
        section_id="Exposition1",
        events=[
            HarmonicEvent(offset=Fraction(0), duration=Fraction(1, 2), chord="Cm"),
            HarmonicEvent(offset=Fraction(1, 2), duration=Fraction(1, 2), chord="Cm"),
        ],
    )

    feedback = check_entries_against_grid(
        skeleton,
        _section(upper, lower),
        {"subject1": e_natural, "subject2": e_flat},
    )

    assert len(feedback) == 1, "one failing slot is one item, not one per note"
    message = feedback[0].message
    assert "E4" in message and "Eb4" in message, "the whole requirement set"
    assert "chords that do" in message
    from cadenzra.notation.chords import parse_chord_symbol
    from cadenzra.verification.section import permitted_pitch_classes

    listed = message.rsplit("chords that do: ", 1)[1].split(" — ")[0]
    suggestions = [symbol.strip() for symbol in listed.split(",")]
    assert len(suggestions) > 1, "several options, so the key's idiom can win"
    for suggestion in suggestions:
        assert {3, 4} <= permitted_pitch_classes(
            parse_chord_symbol(suggestion), strict=True
        ), "every suggested chord holds both notes as real chord tones"


def test_pinned_tones_hand_the_grid_its_constraints_up_front() -> None:
    """A fugue exposition pins tones in every voice at once, and a model shown
    them only as violations fixes one and breaks another until the budget
    dies (live: 8 complaints, then 4, then 8 different ones). The system
    knows every constraint before the first attempt — realized under the
    entry's relation, placed at its bar — so it hands them over. Notes
    shorter than a beat are left free; they read as passing tones."""
    from cadenzra.verification.harmony import pinned_entry_tones

    with_eighth = _notes([60, 55, 63]) + [
        NoteEvent(
            midi_pitch=62,
            onset=Fraction(3, 4),
            duration=Fraction(1, 8),
            velocity=90,
            channel=0,
        )
    ]
    entry = MaterialEntry(
        motif_id="subject1", voice_id="viola", bar=2, relation="P5 up"
    )

    pinned = pinned_entry_tones(_section(entry), {"subject1": with_eighth})

    assert [tone.midi_pitch for tone in pinned] == [67, 62, 70], (
        "realized at the entry's relation; the eighth note is left free"
    )
    assert pinned[0].voice_id == "viola"
    assert pinned[0].onset == Fraction(1), "placed at bar 2 of 4/4"


def test_a_tonal_answer_pins_its_fifth_up_realization() -> None:
    from cadenzra.verification.harmony import pinned_entry_tones

    entry = MaterialEntry(
        motif_id="subject1", voice_id="viola", bar=1, relation="tonal answer"
    )

    pinned = pinned_entry_tones(_section(entry), {"subject1": SUBJECT})

    assert [tone.midi_pitch for tone in pinned] == [67, 62, 70, 69]


def test_the_harmony_loop_threads_the_pinned_tones() -> None:
    from pathlib import Path

    from cadenzra.app.config import RetryBudgets
    from cadenzra.app.pipeline import LayerServices, _harmony_for
    from cadenzra.model.harmony import HarmonicEvent, HarmonicSkeleton
    from cadenzra.model.primitives.pitch import Pitch
    from cadenzra.model.spec import PieceSpec, VoiceSpec
    from cadenzra.model.state import PipelineState
    from cadenzra.model.style import StylePack
    from tests.fakes.generator import ScriptedGenerator

    fitting = HarmonicSkeleton(
        section_id="Exposition1",
        events=[
            HarmonicEvent(offset=Fraction(0), duration=Fraction(4), chord="Cm")
        ],
    )
    generator = ScriptedGenerator(skeletons=[fitting])
    cello = VoiceSpec(
        voice_id="cello",
        kind="instrument",
        range_low=Pitch(step="C", octave=2),
        range_high=Pitch(step="G", octave=4),
        midi_program=42,
    )
    spec = PieceSpec(
        title="T",
        style_prompt="s",
        voices=[cello],
        meters_allowed=[FOUR_FOUR],
        target_minutes=1.0,
    )
    services = LayerServices(
        generator=generator,
        renderer=None,  # type: ignore[arg-type]
        workdir=Path("/tmp/unused"),
        budgets=RetryBudgets(),
    )
    # Cm-compatible subject so the scripted grid validates: C-G-Eb-D quarters.
    subject = _notes([60, 55, 63, 62])

    _harmony_for(
        PipelineState(spec=spec, style=StylePack()),
        services,
        _section(ENTRY),
        StylePack(),
        previous_section=None,
        previous_skeleton=None,
        motif_notes={"subject1": subject},
    )

    (ctx,) = generator.harmony_contexts
    assert [tone.midi_pitch for tone in ctx.pinned] == [60, 55, 63, 62]


def test_a_passing_clash_is_not_flagged() -> None:
    """Same threshold as the downstream held-tone check: a plan-time pass must
    guarantee no unfixable held-tone downstream, no more and no less. The
    eighth is the sharp boundary — an inverted subject's passing eighth once
    demanded a chord containing Ab, C and E at once, six grids running."""
    for duration in (Fraction(1, 16), Fraction(1, 8)):
        quick = [
            NoteEvent(
                midi_pitch=63,
                onset=Fraction(0),
                duration=duration,
                velocity=90,
                channel=0,
            )
        ]

        assert (
            check_entries_against_grid(
                _skeleton("G7"), _section(ENTRY), {"subject1": quick}
            )
            == []
        )
