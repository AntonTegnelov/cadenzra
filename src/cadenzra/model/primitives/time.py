"""The two time registers and the exact conversion between them.

Internally, position is an absolute `Fraction` of whole notes from the start of
a section. Bar-and-beat is a *derived view* computed against the section's
meter — the register musicians and LLMs speak (docs/03).

**The beat unit.** A beat is one unit of the meter's shortest denominator,
counted from 1: 5/4 has beats 1-5 of a quarter note each, 7/8 has beats 1-7 of
an eighth. Grouping (2+2+3) shapes how those beats are *heard* and *printed*,
but it does not renumber them — so the coordinate stays decidable and round-
trips exactly, including under additive meters. The forgiving part of the
surface (a musician's loosely-meant "beat 2.5") is normalized in `llm/parsers/`,
not here.
"""

from fractions import Fraction

from cadenzra.model.primitives.meter import MeterSpec

type Beat = Fraction | int | float


def to_fraction(value: Beat) -> Fraction:
    """Exact `Fraction` for a beat written as a decimal.

    Goes through the decimal *text* so that "2.5" means 5/2 rather than the
    nearest binary double.
    """
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    return Fraction(str(value))


def offset_of(bar: int, beat: Beat, meter: MeterSpec) -> Fraction:
    """Absolute offset from section start for a 1-based bar and beat."""
    beat_value = to_fraction(beat)
    if bar < 1:
        raise ValueError(f"bars are numbered from 1, got {bar}")
    if beat_value < 1:
        raise ValueError(f"beats are numbered from 1, got {beat}")
    return (bar - 1) * meter.bar_length + (beat_value - 1) * meter.unit_length


def bar_beat_of(offset: Fraction, meter: MeterSpec) -> tuple[int, Fraction]:
    """The 1-based bar and beat an absolute offset falls on."""
    if offset < 0:
        raise ValueError(f"offsets are measured from section start, got {offset}")
    bars, within_bar = divmod(offset, meter.bar_length)
    return int(bars) + 1, within_bar / meter.unit_length + 1


def bar_span(bar: int, meter: MeterSpec) -> tuple[Fraction, Fraction]:
    """The half-open offset span [start, end) of a whole bar."""
    start = offset_of(bar, 1, meter)
    return start, start + meter.bar_length


def bar_containing(offset: Fraction, meter: MeterSpec) -> int:
    """Just the bar number — the common case in feedback messages."""
    return bar_beat_of(offset, meter)[0]


def section_length(bars: int, meter: MeterSpec) -> Fraction:
    """The exact length of a section of `bars` bars."""
    if bars < 1:
        raise ValueError(f"a section needs at least one bar, got {bars}")
    return bars * meter.bar_length


def format_bar_beat(offset: Fraction, meter: MeterSpec) -> str:
    """Render a position the way a rehearsal note would: "bar 7, beat 2.5"."""
    bar, beat = bar_beat_of(offset, meter)
    if beat.denominator == 1:
        return f"bar {bar}, beat {beat.numerator}"
    return f"bar {bar}, beat {float(beat):g}"
