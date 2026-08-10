"""Reading a plan's key string — "c minor", "d phrygian", "Bb major".

Two consumers with one parse: assembly turns the key into a `\\key` command,
and the feedback surface asks which way to spell accidentals. Unrecognized
keys answer conservatively (no command, sharp spelling) rather than guessing —
inventing a key signature would silently change what the score says.
"""

from typing import Final

from cadenzra.model.primitives.pitch import Pitch

MODES: Final = frozenset(
    {
        "major", "minor", "ionian", "dorian", "phrygian",
        "lydian", "mixolydian", "aeolian", "locrian",
    }
)

# Semitones from a mode's tonic up to its relative major's tonic.
_RELATIVE_MAJOR_OFFSET: Final[dict[str, int]] = {
    "major": 0,
    "ionian": 0,
    "dorian": 10,
    "phrygian": 8,
    "lydian": 7,
    "mixolydian": 5,
    "minor": 3,
    "aeolian": 3,
    "locrian": 1,
}

# Major keys spelled with flats: F, Bb, Eb, Ab, Db, Gb.
_FLAT_SIDE: Final = frozenset({5, 10, 3, 8, 1, 6})


def parse_key(key: str) -> tuple[Pitch, str] | None:
    """Tonic and mode, or None for anything not confidently readable."""
    words = key.strip().split()
    if not words:
        return None
    try:
        tonic = Pitch.from_scientific(f"{words[0].capitalize()}3")
    except ValueError:
        return None
    mode = words[1].lower() if len(words) > 1 else "major"
    if mode not in MODES:
        return None
    return tonic, mode


def prefer_flats(key: str) -> bool:
    """Whether this key spells its chromatic notes with flats.

    Decided by the relative major's tonic: c minor relates to Eb major, so its
    surface speaks Eb, not D#. An unreadable key answers False — the sharp
    default `Pitch.from_midi_number` already has.
    """
    parsed = parse_key(key)
    if parsed is None:
        return False
    tonic, mode = parsed
    return (tonic.pc12 + _RELATIVE_MAJOR_OFFSET[mode]) % 12 in _FLAT_SIDE
