"""`validate_harmony` — the cheapest, most decidable check in the system.

A skeleton is ordered, gapless, and exactly fills its section, or it is not a
skeleton. All of that is exact `Fraction` arithmetic caught before any notation
exists — floats would mis-sum a page of 7/8 bars and the error would only
surface as a mysterious bar-check failure three layers later (docs/03,
docs/08 principle 3).
"""

from fractions import Fraction
from typing import Final

from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.harmony import HarmonicSkeleton
from cadenzra.model.primitives.time import format_bar_beat, section_length
from cadenzra.model.structure import SectionPlan
from cadenzra.notation.chords import ChordSymbolError, parse_chord_symbol

SOURCE: Final = "validate_harmony"


def validate_harmony(
    skeleton: HarmonicSkeleton, section: SectionPlan
) -> list[FeedbackItem]:
    """Check one section's skeleton. An empty list means it is accepted."""
    expected = section_length(section.bars, section.meter)

    if not skeleton.events:
        return [
            _item(
                section,
                message=(
                    f"section {section.section_id} has no chords; it needs a "
                    f"progression covering all {section.bars} bars"
                ),
            )
        ]

    return [
        *_check_order_and_gaps(skeleton, section),
        *_check_total_length(skeleton, section, expected),
        *_check_symbols(skeleton, section),
    ]


def _check_order_and_gaps(
    skeleton: HarmonicSkeleton, section: SectionPlan
) -> list[FeedbackItem]:
    """Events must run in order and leave no bar unharmonized."""
    feedback = []
    cursor = Fraction(0)
    for event in sorted(skeleton.events, key=lambda item: item.offset):
        if event.offset > cursor:
            feedback.append(
                _item(
                    section,
                    location=cursor,
                    message=(
                        f"nothing is harmonized between "
                        f"{format_bar_beat(cursor, section.meter)} and "
                        f"{format_bar_beat(event.offset, section.meter)}; the "
                        "progression must be gapless"
                    ),
                )
            )
        elif event.offset < cursor:
            feedback.append(
                _item(
                    section,
                    location=event.offset,
                    message=(
                        f"the chord at {format_bar_beat(event.offset, section.meter)} "
                        f"overlaps the one before it, which is still sounding at "
                        f"{format_bar_beat(cursor, section.meter)}"
                    ),
                )
            )
        cursor = max(cursor, event.end)
    return feedback


def _check_total_length(
    skeleton: HarmonicSkeleton, section: SectionPlan, expected: Fraction
) -> list[FeedbackItem]:
    """The progression must fill the section exactly — no more, no less."""
    span = skeleton.span
    if span == expected:
        return []
    bars_covered = span / section.meter.bar_length
    return [
        _item(
            section,
            message=(
                f"the progression covers {_bars_text(bars_covered)} but section "
                f"{section.section_id} is {section.bars} bars of "
                f"{section.meter.surface_string()}; the chord durations must add up "
                "to exactly the section length"
            ),
        )
    ]


def _bars_text(bars: Fraction) -> str:
    if bars.denominator == 1:
        return f"{bars.numerator} bar{'' if bars.numerator == 1 else 's'}"
    return f"{float(bars):.2f} bars"


def _check_symbols(
    skeleton: HarmonicSkeleton, section: SectionPlan
) -> list[FeedbackItem]:
    """Every symbol must be one the alignment checker can read.

    An unparseable chord is not a cosmetic problem: it means the section's
    harmony cannot be verified against its notes at all.
    """
    feedback = []
    for event in skeleton.events:
        try:
            parse_chord_symbol(event.chord)
        except ChordSymbolError as error:
            feedback.append(
                _item(
                    section,
                    location=event.offset,
                    message=(
                        f"the chord {event.chord!r} at "
                        f"{format_bar_beat(event.offset, section.meter)} is not a chord "
                        "symbol the system reads; use forms like Dm, Esus4, F#m7, Bb/D"
                    ),
                    evidence=str(error),
                )
            )
    return feedback


def _item(
    section: SectionPlan,
    *,
    message: str,
    location: Fraction | None = None,
    evidence: str | None = None,
) -> FeedbackItem:
    return FeedbackItem(
        source=SOURCE,
        level="harmony",
        section_id=section.section_id,
        location=location,
        message=message,
        evidence=evidence,
    )
