"""Contracts for meter arithmetic and the bar/beat <-> offset registers.

The round-trip is the load-bearing property: everything internal is keyed by
absolute offset, everything an LLM or musician reads is bar/beat, and a lossy
conversion between them would corrupt positions silently.
"""

from fractions import Fraction

import pytest

from cadenzra.model.primitives.meter import MeterSpec, MeterTerm, simple_meter
from cadenzra.model.primitives.time import (
    bar_beat_of,
    bar_span,
    format_bar_beat,
    offset_of,
    section_length,
)

FOUR_FOUR = simple_meter(4, 4)
FIVE_FOUR = simple_meter(5, 4, [3, 2])
SEVEN_EIGHT = simple_meter(7, 8, [2, 2, 3])
SEVEN_EIGHT_OTHER = simple_meter(7, 8, [3, 2, 2])
SIX_EIGHT = simple_meter(6, 8, [3, 3])
ADDITIVE = MeterSpec(
    terms=[MeterTerm(numerator=3, denominator=4), MeterTerm(numerator=1, denominator=8)],
    grouping=[2, 2, 3],
)

METER_PALETTE = [FOUR_FOUR, FIVE_FOUR, SEVEN_EIGHT, SIX_EIGHT, ADDITIVE]


@pytest.mark.parametrize(
    ("meter", "length", "units"),
    [
        (FOUR_FOUR, Fraction(1), 4),
        (FIVE_FOUR, Fraction(5, 4), 5),
        (SEVEN_EIGHT, Fraction(7, 8), 7),
        (SIX_EIGHT, Fraction(3, 4), 6),
        (ADDITIVE, Fraction(7, 8), 7),
    ],
)
def test_bar_length_is_exact(meter: MeterSpec, length: Fraction, units: int) -> None:
    assert meter.bar_length == length
    assert meter.units_per_bar == units


def test_additive_meter_borrows_the_shortest_term_as_its_unit() -> None:
    assert ADDITIVE.is_additive
    assert ADDITIVE.unit == 8
    assert ADDITIVE.bar_length == SEVEN_EIGHT.bar_length


def test_seven_eight_bars_sum_exactly_over_a_long_section() -> None:
    assert section_length(64, SEVEN_EIGHT) == Fraction(64 * 7, 8)


@pytest.mark.parametrize(
    ("meter", "expected"),
    [
        (SEVEN_EIGHT, "7/8 (2+2+3)"),
        (SEVEN_EIGHT_OTHER, "7/8 (3+2+2)"),
        (FOUR_FOUR, "4/4"),
        (ADDITIVE, "3/4+1/8 (2+2+3)"),
    ],
)
def test_surface_string_reads_like_a_musician_wrote_it(meter: MeterSpec, expected: str) -> None:
    assert meter.surface_string() == expected


def test_the_two_seven_eight_groupings_are_different_meters() -> None:
    assert SEVEN_EIGHT != SEVEN_EIGHT_OTHER
    assert SEVEN_EIGHT.bar_length == SEVEN_EIGHT_OTHER.bar_length


def test_irrational_meters_are_refused() -> None:
    with pytest.raises(ValueError, match="power of two"):
        MeterTerm(numerator=4, denominator=3)


def test_grouping_must_account_for_the_whole_bar() -> None:
    with pytest.raises(ValueError, match="sums to"):
        simple_meter(7, 8, [2, 2, 2])


@pytest.mark.parametrize(
    ("bar", "beat", "meter", "offset"),
    [
        (1, 1, FOUR_FOUR, Fraction(0)),
        (2, 1, FOUR_FOUR, Fraction(1)),
        (1, 3, FOUR_FOUR, Fraction(1, 2)),
        (1, 2.5, FOUR_FOUR, Fraction(3, 8)),
        (1, 1, SEVEN_EIGHT, Fraction(0)),
        (1, 6, SEVEN_EIGHT, Fraction(5, 8)),
        (3, 1, SEVEN_EIGHT, Fraction(14, 8)),
        (2, 4, ADDITIVE, Fraction(7, 8) + Fraction(3, 8)),
    ],
)
def test_bar_beat_maps_to_the_expected_offset(
    bar: int, beat: float, meter: MeterSpec, offset: Fraction
) -> None:
    assert offset_of(bar, beat, meter) == offset


@pytest.mark.parametrize("meter", METER_PALETTE)
@pytest.mark.parametrize("bar", [1, 2, 9, 64])
def test_round_trip_is_identity_for_every_beat_the_surface_can_express(
    meter: MeterSpec, bar: int
) -> None:
    for unit in range(meter.units_per_bar):
        for fraction_of_beat in (Fraction(0), Fraction(1, 2), Fraction(1, 3), Fraction(3, 4)):
            beat = 1 + unit + fraction_of_beat
            assert bar_beat_of(offset_of(bar, beat, meter), meter) == (bar, beat)


@pytest.mark.parametrize("meter", METER_PALETTE)
def test_bars_tile_the_timeline_without_gap_or_overlap(meter: MeterSpec) -> None:
    for bar in range(1, 9):
        start, end = bar_span(bar, meter)
        assert end - start == meter.bar_length
        assert bar_span(bar + 1, meter)[0] == end
        assert bar_beat_of(start, meter) == (bar, Fraction(1))


def test_positions_before_the_section_start_are_refused() -> None:
    with pytest.raises(ValueError, match="numbered from 1"):
        offset_of(0, 1, FOUR_FOUR)
    with pytest.raises(ValueError, match="numbered from 1"):
        offset_of(1, 0, FOUR_FOUR)
    with pytest.raises(ValueError, match="section start"):
        bar_beat_of(Fraction(-1, 8), FOUR_FOUR)


@pytest.mark.parametrize(
    ("offset", "meter", "expected"),
    [
        (Fraction(0), SEVEN_EIGHT, "bar 1, beat 1"),
        (Fraction(5, 8), SEVEN_EIGHT, "bar 1, beat 6"),
        (Fraction(3, 8), FOUR_FOUR, "bar 1, beat 2.5"),
    ],
)
def test_positions_render_as_rehearsal_notes(
    offset: Fraction, meter: MeterSpec, expected: str
) -> None:
    assert format_bar_beat(offset, meter) == expected
