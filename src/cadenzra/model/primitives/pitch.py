"""Tuning-agnostic pitch, and the name surfaces that print it.

`Pitch` is deliberately more general than 12-EDO: `alteration` is an exact
`Fraction` of a whole tone, so quarter-tones (and anything finer) are
representable at the type level even though the pipeline does not compose with
them (docs/03). The 12-EDO world — pitch classes, semitone arithmetic — is a
*derived view*, and it refuses to guess: asking a three-quarter-sharp for its
pitch class raises rather than rounding, because a silently rounded pitch is
exactly the kind of plausible-but-wrong artifact this system exists to prevent
(docs/08, principle 4).
"""

from fractions import Fraction
from typing import Final, Literal, Self

from pydantic import BaseModel

Step = Literal["C", "D", "E", "F", "G", "A", "B"]

STEP_SEMITONES: Final[dict[Step, int]] = {
    "C": 0,
    "D": 2,
    "E": 4,
    "F": 5,
    "G": 7,
    "A": 9,
    "B": 11,
}
_SEMITONE_STEPS: Final[dict[int, Step]] = {v: k for k, v in STEP_SEMITONES.items()}

CENTS_PER_WHOLE_TONE: Final = 200
CENTS_PER_SEMITONE: Final = 100

# LilyPond's default (Dutch) note language, keyed by quarter-tones of alteration.
_LILY_ACCIDENTALS: Final[dict[int, str]] = {
    -4: "eses",
    -3: "eseh",
    -2: "es",
    -1: "eh",
    0: "",
    1: "ih",
    2: "is",
    3: "isih",
    4: "isis",
}
_LILY_TO_QUARTERS: Final[dict[str, int]] = {v: k for k, v in _LILY_ACCIDENTALS.items()}

# Scientific notation: "#"/"b" carry semitones, "+"/"d" the quarter-tone.
# "d" (demi-flat) rather than "-" so that a negative octave — "C-1" is MIDI 0 —
# can never be read as a quarter-flat. Quarter-tones are gated out of every LLM
# surface (docs/04), so this spelling is only ever read by us.
_SCIENTIFIC_ACCIDENTALS: Final[dict[int, str]] = {
    -4: "bb",
    -3: "bd",
    -2: "b",
    -1: "d",
    0: "",
    1: "+",
    2: "#",
    3: "#+",
    4: "##",
}
_SCIENTIFIC_TO_QUARTERS: Final[dict[str, int]] = {
    v: k for k, v in _SCIENTIFIC_ACCIDENTALS.items()
}

# LilyPond's unmarked octave is the one below middle C: `c` is C3, `c'` is C4.
_LILY_BASE_OCTAVE: Final = 3


def _is_octave_number(text: str) -> bool:
    return text.removeprefix("-").isdigit()


class UnnameablePitchError(ValueError):
    """The pitch is finer than the note-name surfaces can spell.

    `Pitch` accepts any `Fraction` alteration so that microtonality is not
    foreclosed at the type level; the *names* only reach quarter-tones. This
    error marks that boundary honestly rather than rounding across it.
    """


class NotTwelveEdoError(ValueError):
    """A 12-EDO view was requested of a pitch that is not in 12-EDO."""


class Pitch(BaseModel, frozen=True):
    """A written pitch: step, alteration in whole tones, octave.

    C4 is middle C. `alteration` follows docs/03: 1/2 is a sharp, -1/2 a flat,
    1/4 a quarter-sharp.
    """

    step: Step
    alteration: Fraction = Fraction(0)
    octave: int

    @property
    def cents(self) -> Fraction:
        """Absolute pitch height in cents, with C-1 (MIDI 0) as zero.

        This is the coordinate every comparison and range check uses, because
        it is the only one that stays meaningful for non-12-EDO alterations.
        """
        semitones = (self.octave + 1) * 12 + STEP_SEMITONES[self.step]
        return semitones * CENTS_PER_SEMITONE + self.alteration * CENTS_PER_WHOLE_TONE

    @property
    def quarter_tones(self) -> int:
        """Alteration in quarter-tones. Raises if the pitch is finer than that."""
        quarters = self.alteration * 4
        if quarters.denominator != 1:
            raise UnnameablePitchError(
                f"alteration {self.alteration} of a whole tone is finer than a "
                "quarter-tone and has no note-name spelling"
            )
        return int(quarters)

    @property
    def pc12(self) -> int:
        """Pitch class in 12-EDO — the derived view chord logic works in."""
        semitones = self.alteration * 2
        if semitones.denominator != 1:
            raise NotTwelveEdoError(
                f"{self!r} has a microtonal alteration and no 12-EDO pitch class"
            )
        return (STEP_SEMITONES[self.step] + int(semitones)) % 12

    @property
    def midi_number(self) -> int:
        """MIDI note number. Raises for microtonal pitches, same as `pc12`."""
        semitones = self.alteration * 2
        if semitones.denominator != 1:
            raise NotTwelveEdoError(
                f"{self!r} has a microtonal alteration and no MIDI note number"
            )
        return (self.octave + 1) * 12 + STEP_SEMITONES[self.step] + int(semitones)

    def is_within(self, low: Pitch, high: Pitch) -> bool:
        """Range check in cents — the form every voice-range validator uses."""
        return low.cents <= self.cents <= high.cents

    def to_scientific(self) -> str:
        return f"{self.step}{_SCIENTIFIC_ACCIDENTALS[self.quarter_tones]}{self.octave}"

    def to_lilypond(self) -> str:
        name = self.step.lower() + _LILY_ACCIDENTALS[self.quarter_tones]
        if self.octave >= _LILY_BASE_OCTAVE:
            return name + "'" * (self.octave - _LILY_BASE_OCTAVE)
        return name + "," * (_LILY_BASE_OCTAVE - self.octave)

    @classmethod
    def from_scientific(cls, text: str) -> Self:
        body = text.strip()
        if not body or body[0].upper() not in STEP_SEMITONES:
            raise ValueError(f"{text!r} does not start with a note name A-G")
        step: Step = body[0].upper()  # type: ignore[assignment]

        rest = body[1:]
        # Longest accidental first, so "bb" is never read as "b" plus junk.
        for accidental in sorted(_SCIENTIFIC_TO_QUARTERS, key=len, reverse=True):
            octave_text = rest.removeprefix(accidental)
            if rest.startswith(accidental) and _is_octave_number(octave_text):
                return cls(
                    step=step,
                    alteration=Fraction(_SCIENTIFIC_TO_QUARTERS[accidental], 4),
                    octave=int(octave_text),
                )
        raise ValueError(f"{text!r} is not an accidental followed by an octave number")

    @classmethod
    def from_lilypond(cls, text: str) -> Self:
        body = text.strip()
        octave = _LILY_BASE_OCTAVE
        while body and body[-1] in "',":
            octave += 1 if body[-1] == "'" else -1
            body = body[:-1]

        if not body or body[0].upper() not in STEP_SEMITONES:
            raise ValueError(f"{text!r} does not start with a note name a-g")
        step: Step = body[0].upper()  # type: ignore[assignment]

        accidental = body[1:]
        if accidental not in _LILY_TO_QUARTERS:
            raise ValueError(f"{text!r} has an unrecognized accidental {accidental!r}")

        return cls(
            step=step,
            alteration=Fraction(_LILY_TO_QUARTERS[accidental], 4),
            octave=octave,
        )

    @classmethod
    def from_midi_number(cls, number: int, *, prefer_flats: bool = False) -> Self:
        """Spell a MIDI number naturally.

        MIDI carries no spelling, so this is a convention, not a recovery: it
        exists to name pitches in feedback messages ("d''4 exceeds the alto
        ceiling"), never to decide enharmonic correctness — which docs/05 puts
        out of validator scope precisely because MIDI cannot see it.
        """
        octave, semitone = divmod(number, 12)
        if semitone in _SEMITONE_STEPS:
            return cls(step=_SEMITONE_STEPS[semitone], alteration=Fraction(0), octave=octave - 1)
        if prefer_flats:
            return cls(
                step=_SEMITONE_STEPS[semitone + 1],
                alteration=Fraction(-1, 2),
                octave=octave - 1,
            )
        return cls(
            step=_SEMITONE_STEPS[semitone - 1], alteration=Fraction(1, 2), octave=octave - 1
        )
