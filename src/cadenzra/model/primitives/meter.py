"""Meter: simple, compound, and additive, with explicit beat grouping.

Bar length is an exact `Fraction` of whole notes, because 7/8 bars summed in
floats do not close (docs/08, principle 3). Beat grouping is first-class: 7/8
as 2+2+3 and as 3+2+2 are different musical statements and the system must be
able to say which one it means (docs/01).

Rendering a meter *as LilyPond* deliberately lives in `notation/`, not here —
`model/` stays free of notation text.
"""

from fractions import Fraction
from typing import Self

from pydantic import BaseModel, model_validator


class MeterTerm(BaseModel, frozen=True):
    """One term of a time signature, e.g. the 3/4 in 3/4+1/8."""

    numerator: int
    denominator: int

    @model_validator(mode="after")
    def _check_term(self) -> Self:
        if self.numerator < 1:
            raise ValueError(f"meter numerator must be positive, got {self.numerator}")
        if self.denominator < 1 or self.denominator & (self.denominator - 1):
            # Irrational meters (4/3 and friends) are a stated non-goal (docs/01).
            raise ValueError(
                f"meter denominator must be a power of two, got {self.denominator}"
            )
        return self

    @property
    def length(self) -> Fraction:
        """This term's length in whole notes."""
        return Fraction(self.numerator, self.denominator)

    def __str__(self) -> str:
        return f"{self.numerator}/{self.denominator}"


class MeterSpec(BaseModel, frozen=True):
    """A time signature: one term for simple/compound, several for additive.

    `grouping` counts units of the shortest term — [2, 2, 3] for 7/8.
    """

    terms: list[MeterTerm]
    grouping: list[int] | None = None

    @model_validator(mode="after")
    def _check_spec(self) -> Self:
        if not self.terms:
            raise ValueError("a meter needs at least one term")
        if self.grouping is None:
            return self
        if any(count < 1 for count in self.grouping):
            raise ValueError(f"grouping counts must be positive, got {self.grouping}")
        if sum(self.grouping) != self.units_per_bar:
            raise ValueError(
                f"grouping {self.grouping} sums to {sum(self.grouping)}, but "
                f"{self.surface_string_bare()} holds {self.units_per_bar} "
                f"{self.unit}-note units per bar"
            )
        return self

    @property
    def bar_length(self) -> Fraction:
        """The exact length of one bar, in whole notes."""
        return sum((term.length for term in self.terms), Fraction(0))

    @property
    def unit(self) -> int:
        """The denominator of the shortest term — the unit `grouping` counts."""
        return max(term.denominator for term in self.terms)

    @property
    def unit_length(self) -> Fraction:
        """The length of one grouping unit, in whole notes."""
        return Fraction(1, self.unit)

    @property
    def units_per_bar(self) -> int:
        """How many grouping units fill a bar. Exact by construction.

        Every denominator is a power of two and `unit` is the largest of them,
        so this division is always exact — no rounding decision to make.
        """
        return int(self.bar_length / self.unit_length)

    @property
    def is_additive(self) -> bool:
        return len(self.terms) > 1

    def surface_string_bare(self) -> str:
        """The signature without its grouping: "7/8", "3/4+1/8"."""
        return "+".join(str(term) for term in self.terms)

    def surface_string(self) -> str:
        """How a musician would write it: "7/8 (2+2+3)", "3/4+1/8"."""
        bare = self.surface_string_bare()
        if self.grouping is None:
            return bare
        return f"{bare} ({'+'.join(str(count) for count in self.grouping)})"

    def __str__(self) -> str:
        return self.surface_string()


def simple_meter(numerator: int, denominator: int, grouping: list[int] | None = None) -> MeterSpec:
    """Shorthand for the common single-term case."""
    return MeterSpec(
        terms=[MeterTerm(numerator=numerator, denominator=denominator)], grouping=grouping
    )
