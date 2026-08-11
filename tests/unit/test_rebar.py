"""Rebarring a prescribed entry into the section's meter, in range.

An entry is 100% prescribed — its pitches, rhythm, and (up to a whole octave)
its register are all determined the moment the plan declares it. The evening
forensics showed the model failing the arithmetic of that determinism 30/30
times when handed the puzzle; these pin the machinery that hands it the
answer instead (docs/08 principle 2, `material_text`'s own doctrine).
"""

from fractions import Fraction

from cadenzra.model.primitives.meter import simple_meter
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.notation.rebar import octave_displacement, rebar_events
from cadenzra.verification.midi_analysis import NoteEvent

FOUR_FOUR = simple_meter(4, 4)
FIVE_FOUR = simple_meter(5, 4, [3, 2])
SEVEN_EIGHT = simple_meter(7, 8, [2, 2, 3])

G3 = Pitch(step="G", octave=3)
C6 = Pitch(step="C", octave=6)


def _note(pitch: int, onset: Fraction, duration: Fraction) -> NoteEvent:
    return NoteEvent(
        midi_pitch=pitch, onset=onset, duration=duration, velocity=64, channel=0
    )


def _line(*notes: tuple[int, str]) -> list[NoteEvent]:
    """Consecutive notes from (midi_pitch, duration-fraction-text) pairs."""
    events = []
    cursor = Fraction(0)
    for pitch, duration in notes:
        length = Fraction(duration)
        events.append(_note(pitch, cursor, length))
        cursor += length
    return events


# --- octave_displacement ----------------------------------------------------


def test_a_low_subject_is_lifted_by_exactly_one_octave() -> None:
    """The double-fugue shape: an answer descending to D3 against a G3 floor
    fits at +12 and the checker hears intervals, so +12 is the answer."""
    assert octave_displacement([50, 51, 53, 55, 57], G3, C6) == 12


def test_an_in_range_line_needs_no_shift() -> None:
    assert octave_displacement([60, 64, 67], G3, C6) == 0


def test_no_whole_octave_placement_returns_none() -> None:
    """The span fits but no k*12 lands inside — the hole the span-only motif
    check admits (D3-start line spanning 26 semitones vs G3–C6)."""
    assert octave_displacement([50, 76], G3, C6) is None


def test_the_smallest_shift_wins() -> None:
    assert octave_displacement([80, 82], G3, C6) == 0
    assert octave_displacement([92, 94], G3, C6) == -12


# --- rebar_events -----------------------------------------------------------


def test_a_bar_of_quarters_rebars_verbatim_in_its_own_meter() -> None:
    events = _line((64, "1/4"), (64, "1/8"), (64, "1/8"), (64, "1/4"), (66, "1/4"))

    text = rebar_events(events, FOUR_FOUR, prefer_flats=False)

    assert text == "e'4 e'8 e'8 e'4 fis'4 |"


def test_a_two_bar_4_4_theme_rebars_into_5_4_with_the_barline_moved() -> None:
    """The longform trap: the theme's internal 4/4 barline landed one quarter
    short of the section's real barline. Rebarred, the first 5/4 bar simply
    continues into the theme's second half — no tie needed here."""
    events = _line(
        (64, "1/4"), (64, "1/8"), (64, "1/8"), (64, "1/4"), (66, "1/4"),
        (67, "1/4"), (69, "1/8"), (71, "1/8"), (67, "1/4"), (64, "1/4"),
    )

    text = rebar_events(events, FIVE_FOUR, prefer_flats=False)

    assert text is not None
    assert text.startswith("e'4 e'8 e'8 e'4 fis'4 g'4 |"), text
    assert "a'8 b'8 g'4 e'4" in text


def test_a_note_cut_by_the_new_barline_is_split_with_a_tie() -> None:
    """A half note starting on beat 3 of 7/8 crosses the barline: 3/8 in this
    bar tied to 1/8 in the next."""
    events = _line((72, "1/4"), (72, "1/4"), (72, "1/2"))

    text = rebar_events(events, SEVEN_EIGHT, prefer_flats=False)

    assert text == "c''4 c''4 c''4.~ | c''8"


def test_gaps_between_notes_become_rests() -> None:
    events = [
        _note(60, Fraction(0), Fraction(1, 4)),
        _note(62, Fraction(1, 2), Fraction(1, 2)),
    ]

    text = rebar_events(events, FOUR_FOUR, prefer_flats=False)

    assert text == "c'4 r4 d'2 |"


def test_flat_side_keys_spell_flats() -> None:
    events = _line((63, "1/4"))

    assert rebar_events(events, FOUR_FOUR, prefer_flats=True) == "ees'4"
    assert rebar_events(events, FOUR_FOUR, prefer_flats=False) == "dis'4"


def test_tuplet_durations_are_not_representable_and_return_none() -> None:
    events = _line((60, "1/6"), (62, "1/6"), (64, "1/6"))

    assert rebar_events(events, FOUR_FOUR, prefer_flats=False) is None


def test_overlapping_events_return_none() -> None:
    events = [
        _note(60, Fraction(0), Fraction(1, 2)),
        _note(64, Fraction(1, 4), Fraction(1, 4)),
    ]

    assert rebar_events(events, FOUR_FOUR, prefer_flats=False) is None
