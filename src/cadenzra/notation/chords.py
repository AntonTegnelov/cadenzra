"""Chord symbols to pitch-class sets.

The harmonic-alignment validator needs to know which pitches a chord contains;
this is the small parser that tells it (docs/03). It works in the 12-EDO view
of `Pitch` — chord symbols are a 12-EDO idea, and a symbol has nothing to say
about quarter-tones.

An unparseable symbol is a validator failure, not a shrug: it means the harmony
generator emitted something nobody can check against.
"""

import re
from typing import Final

from pydantic import BaseModel

_ROOT_SEMITONES: Final[dict[str, int]] = {
    "C": 0,
    "D": 2,
    "E": 4,
    "F": 5,
    "G": 7,
    "A": 9,
    "B": 11,
}

# Intervals above the root, in semitones. Longest names must be tried first, so
# "maj7" is never read as "m" plus junk — the table is ordered by length below.
_QUALITY_INTERVALS: Final[dict[str, tuple[int, ...]]] = {
    "": (0, 4, 7),
    "maj": (0, 4, 7),
    "M": (0, 4, 7),
    "m": (0, 3, 7),
    "min": (0, 3, 7),
    "-": (0, 3, 7),
    "dim": (0, 3, 6),
    "o": (0, 3, 6),
    "aug": (0, 4, 8),
    "+": (0, 4, 8),
    "5": (0, 7),
    "sus2": (0, 2, 7),
    "sus4": (0, 5, 7),
    "sus": (0, 5, 7),
    "6": (0, 4, 7, 9),
    "m6": (0, 3, 7, 9),
    "7": (0, 4, 7, 10),
    "maj7": (0, 4, 7, 11),
    "M7": (0, 4, 7, 11),
    "m7": (0, 3, 7, 10),
    "min7": (0, 3, 7, 10),
    "mmaj7": (0, 3, 7, 11),
    "m7b5": (0, 3, 6, 10),
    "dim7": (0, 3, 6, 9),
    "o7": (0, 3, 6, 9),
    "7sus4": (0, 5, 7, 10),
    "add9": (0, 2, 4, 7),
    "madd9": (0, 2, 3, 7),
    "9": (0, 2, 4, 7, 10),
    "maj9": (0, 2, 4, 7, 11),
    "m9": (0, 2, 3, 7, 10),
    "11": (0, 2, 4, 5, 7, 10),
    "13": (0, 2, 4, 7, 9, 10),
}

_SYMBOL = re.compile(r"^(?P<root>[A-Ga-g][#b]?)(?P<quality>[^/]*)(?:/(?P<bass>[A-Ga-g][#b]?))?$")


class ChordSymbolError(ValueError):
    """The chord symbol is not in the vocabulary the alignment check reads."""


class ParsedChord(BaseModel, frozen=True):
    """A chord symbol reduced to what an alignment check can use."""

    symbol: str
    root_pc: int
    quality: str
    bass_pc: int | None = None
    pitch_classes: frozenset[int]

    def contains(self, pitch_class: int) -> bool:
        return pitch_class in self.pitch_classes


def parse_chord_symbol(symbol: str) -> ParsedChord:
    """Parse "Dm", "Esus4/B", "D5" into a pitch-class set."""
    text = symbol.strip()
    match = _SYMBOL.match(text)
    if match is None:
        raise ChordSymbolError(f"{symbol!r} is not a chord symbol")

    root_pc = _root_pitch_class(match["root"])
    quality = match["quality"].strip()
    if quality not in _QUALITY_INTERVALS:
        raise ChordSymbolError(
            f"{symbol!r} has unknown chord quality {quality!r}; known qualities are "
            f"{sorted(name for name in _QUALITY_INTERVALS if name)}"
        )

    bass_pc = _root_pitch_class(match["bass"]) if match["bass"] else None
    pitch_classes = {(root_pc + step) % 12 for step in _QUALITY_INTERVALS[quality]}
    if bass_pc is not None:
        pitch_classes.add(bass_pc)

    return ParsedChord(
        symbol=text,
        root_pc=root_pc,
        quality=quality,
        bass_pc=bass_pc,
        pitch_classes=frozenset(pitch_classes),
    )


def _root_pitch_class(name: str) -> int:
    step = _ROOT_SEMITONES[name[0].upper()]
    if name[1:] == "#":
        return (step + 1) % 12
    if name[1:] == "b":
        return (step - 1) % 12
    return step
