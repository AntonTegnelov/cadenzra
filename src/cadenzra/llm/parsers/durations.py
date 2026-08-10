"""Declared duration arithmetic — the forcing function for meter-true bars.

A model that cannot be trusted to make its bars add up *can* be made to show
its arithmetic in a channel a parser can sum exactly. Every notation-writing
tool that carries a duration declaration is checked here, bar by bar, before
anything compiles: a copied or miscounted rhythm fails with both numbers in
the message. The parser judges only the declaration — whether the written
notes match it is still the compiler's question (docs/08).
"""

from fractions import Fraction

from cadenzra.common.errors import LLMOutputError
from cadenzra.model.primitives.meter import MeterSpec

_PLAIN_VALUES = frozenset({1, 2, 4, 8, 16, 32, 64, 128})


def duration_value(token: str) -> Fraction:
    """One declared duration: "4", "8.", "16..", or a real length like "1/6"."""
    if "/" in token:
        try:
            return Fraction(token)
        except (ValueError, ZeroDivisionError):
            raise LLMOutputError(f"unreadable duration {token!r}") from None
    base = token.rstrip(".")
    dots = len(token) - len(base)
    if not base.isdigit() or int(base) not in _PLAIN_VALUES:
        raise LLMOutputError(
            f"unreadable duration {token!r}; declare plain values (4, 8., 16) "
            "or a real length like 1/6 for a tuplet note"
        )
    return Fraction(1, int(base)) * (2 - Fraction(1, 2**dots))


def duration_token(value: Fraction) -> str | None:
    """The plain token for a length, dots included — None when there is none."""
    for base in sorted(_PLAIN_VALUES):
        length = Fraction(1, base)
        for dots in (0, 1, 2):
            if length * (2 - Fraction(1, 2**dots)) == value:
                return f"{base}{'.' * dots}"
    return None


def check_declared_bars(
    declaration: str, *, bars: int, meter: MeterSpec, what: str
) -> None:
    """Every `|`-separated group must sum to one bar, and the count must match."""
    bar_length = meter.bar_length
    groups = [group for group in (g.strip() for g in declaration.split("|")) if group]
    if len(groups) != bars:
        run_total = sum(
            (duration_value(token) for group in groups for token in group.split()),
            Fraction(0),
        )
        if len(groups) == 1 and run_total == bars * bar_length:
            # The arithmetic is right; only the separators are missing.
            raise LLMOutputError(
                f"{what} declares all its durations as one run — put a | "
                f"between bars, so the declaration has {bars} groups like the "
                "music has bars"
            )
        raise LLMOutputError(
            f"{what} declares durations for "
            f"{len(groups)} bar{'' if len(groups) == 1 else 's'} but must fill "
            f"{bars} bars, each summing to one bar of {meter.surface_string()}"
        )
    for index, group in enumerate(groups, 1):
        total = sum((duration_value(token) for token in group.split()), Fraction(0))
        if total == bar_length:
            continue
        difference = bar_length - total
        adjust = (
            f"{difference} of a whole note more is needed"
            if difference > 0
            else f"{-difference} of a whole note must go"
        )
        raise LLMOutputError(
            f"{what}: the declared durations for bar {index} sum to {total} "
            f"of a whole note, but one bar of {meter.surface_string()} holds "
            f"{bar_length} — {adjust}; recount, then write notes to match"
        )
