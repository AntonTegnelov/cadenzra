"""Contracts for `Pitch`: exact heights, honest refusals, lossless names."""

from fractions import Fraction

import pytest

from cadenzra.model.primitives.pitch import (
    NotTwelveEdoError,
    Pitch,
    UnnameablePitchError,
)

SHARP = Fraction(1, 2)
FLAT = Fraction(-1, 2)
QUARTER_SHARP = Fraction(1, 4)
QUARTER_FLAT = Fraction(-1, 4)


def test_middle_c_anchors_the_cents_scale() -> None:
    assert Pitch(step="C", octave=4).midi_number == 60
    assert Pitch(step="C", octave=4).cents == 6000


def test_a440_is_where_it_should_be() -> None:
    assert Pitch(step="A", octave=4).midi_number == 69


def test_quarter_sharp_sits_fifty_cents_above_its_natural() -> None:
    natural = Pitch(step="C", octave=4)
    raised = Pitch(step="C", alteration=QUARTER_SHARP, octave=4)

    assert raised.cents - natural.cents == 50


def test_enharmonics_share_a_height_but_not_an_identity() -> None:
    c_sharp = Pitch(step="C", alteration=SHARP, octave=4)
    d_flat = Pitch(step="D", alteration=FLAT, octave=4)

    assert c_sharp.cents == d_flat.cents
    assert c_sharp != d_flat


@pytest.mark.parametrize(
    ("pitch", "expected"),
    [
        (Pitch(step="C", octave=4), 0),
        (Pitch(step="B", alteration=SHARP, octave=3), 0),
        (Pitch(step="E", alteration=FLAT, octave=2), 3),
        (Pitch(step="G", octave=5), 7),
    ],
)
def test_pitch_class_is_a_twelve_edo_view(pitch: Pitch, expected: int) -> None:
    assert pitch.pc12 == expected


def test_microtones_refuse_the_twelve_edo_view_rather_than_rounding() -> None:
    quarter_sharp = Pitch(step="C", alteration=QUARTER_SHARP, octave=4)

    with pytest.raises(NotTwelveEdoError):
        _ = quarter_sharp.pc12
    with pytest.raises(NotTwelveEdoError):
        _ = quarter_sharp.midi_number


def test_alterations_finer_than_a_quarter_tone_are_representable_but_unnameable() -> None:
    sixth_tone = Pitch(step="C", alteration=Fraction(1, 6), octave=4)

    assert sixth_tone.cents == Fraction(6000) + Fraction(200, 6)
    with pytest.raises(UnnameablePitchError):
        sixth_tone.to_lilypond()


RANGE_LOW = Pitch(step="C", octave=4)
RANGE_HIGH = Pitch(step="A", octave=5)


@pytest.mark.parametrize(
    ("pitch", "inside"),
    [
        (Pitch(step="C", octave=4), True),
        (Pitch(step="A", octave=5), True),
        (Pitch(step="B", octave=3), False),
        (Pitch(step="B", alteration=FLAT, octave=5), False),
        (Pitch(step="A", alteration=QUARTER_SHARP, octave=5), False),
    ],
)
def test_range_checks_compare_in_cents(pitch: Pitch, inside: bool) -> None:
    assert pitch.is_within(RANGE_LOW, RANGE_HIGH) is inside


@pytest.mark.parametrize(
    ("pitch", "lily", "scientific"),
    [
        (Pitch(step="C", octave=3), "c", "C3"),
        (Pitch(step="C", octave=4), "c'", "C4"),
        (Pitch(step="G", octave=2), "g,", "G2"),
        (Pitch(step="C", octave=6), "c'''", "C6"),
        (Pitch(step="F", alteration=SHARP, octave=4), "fis'", "F#4"),
        (Pitch(step="E", alteration=FLAT, octave=3), "ees", "Eb3"),
        (Pitch(step="A", alteration=FLAT, octave=5), "aes''", "Ab5"),
        (Pitch(step="C", alteration=Fraction(1), octave=4), "cisis'", "C##4"),
        (Pitch(step="B", alteration=Fraction(-1), octave=2), "beses,", "Bbb2"),
        (Pitch(step="C", alteration=QUARTER_SHARP, octave=4), "cih'", "C+4"),
        (Pitch(step="D", alteration=QUARTER_FLAT, octave=4), "deh'", "Dd4"),
        (Pitch(step="F", alteration=Fraction(3, 4), octave=4), "fisih'", "F#+4"),
        (Pitch(step="G", alteration=Fraction(-3, 4), octave=4), "geseh'", "Gbd4"),
    ],
)
def test_names_round_trip_losslessly(pitch: Pitch, lily: str, scientific: str) -> None:
    assert pitch.to_lilypond() == lily
    assert pitch.to_scientific() == scientific
    assert Pitch.from_lilypond(lily) == pitch
    assert Pitch.from_scientific(scientific) == pitch


def test_negative_octaves_parse_as_octaves_not_quarter_flats() -> None:
    assert Pitch.from_scientific("C-1") == Pitch(step="C", octave=-1)
    assert Pitch.from_scientific("C-1").midi_number == 0


@pytest.mark.parametrize("text", ["H4", "C", "Cq4", "4"])
def test_unparseable_scientific_names_raise(text: str) -> None:
    with pytest.raises(ValueError):
        Pitch.from_scientific(text)


@pytest.mark.parametrize("text", ["h'", "cq'", "'"])
def test_unparseable_lilypond_names_raise(text: str) -> None:
    with pytest.raises(ValueError):
        Pitch.from_lilypond(text)


@pytest.mark.parametrize("number", [0, 21, 60, 61, 69, 108, 127])
def test_midi_spelling_recovers_the_number_it_was_given(number: int) -> None:
    assert Pitch.from_midi_number(number).midi_number == number
    assert Pitch.from_midi_number(number, prefer_flats=True).midi_number == number
