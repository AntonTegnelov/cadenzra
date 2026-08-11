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


def test_a_passing_clash_is_not_flagged() -> None:
    """Same threshold as the downstream held-tone check: a plan-time pass must
    guarantee no unfixable held-tone downstream, no more and no less."""
    quick = [
        NoteEvent(
            midi_pitch=63,
            onset=Fraction(0),
            duration=Fraction(1, 16),
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
