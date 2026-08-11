"""Rebarring a prescribed entry into the section's meter, in range.

A declared entry is fully determined: its pitches and rhythm come from the
motif, its transform from the plan, and — because every downstream check
hears intervals and pitch classes, never absolute octave — its register is
free only up to a whole-octave shift, which is computable against the
voice's range. This module does that arithmetic once, exactly, so the prompt
can hand the composer the finished bars instead of a puzzle three
instructions deep (docs/08 principle 2).

Everything here works on *compiled* note events, never on LilyPond text
(CLAUDE.md: pitch and timing analysis reads the compiled MIDI). The output
is LilyPond because that is the musician surface the model writes.
"""

from fractions import Fraction

from cadenzra.model.primitives.meter import MeterSpec
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.verification.midi_analysis import NoteEvent

# 1 whole note = this many cents of range arithmetic (Pitch.cents is per
# semitone * 100).
_CENTS_PER_SEMITONE = 100

# Plain LilyPond duration denominators, largest value first.
_PLAIN = (1, 2, 4, 8, 16, 32, 64, 128)


def octave_displacement(pitches: list[int], low: Pitch, high: Pitch) -> int | None:
    """The smallest whole-octave shift placing every pitch inside the range.

    Returned in semitones (0, ±12, ±24, …); None when no shift works — a
    line wider than the voice, or one whose octave positions straddle both
    limits. The smallest |shift| wins so the entry stays as close to its
    written register as the range allows.
    """
    if not pitches:
        return 0
    for magnitude in range(0, 8):
        for octaves in {magnitude, -magnitude}:
            shift = 12 * octaves
            if all(
                low.cents <= (pitch + shift) * _CENTS_PER_SEMITONE <= high.cents
                for pitch in pitches
            ):
                return shift
    return None


def _tokens(value: Fraction) -> list[str] | None:
    """A duration as LilyPond tokens summing exactly to it, or None.

    A single plain or dotted value is preferred; anything else decomposes
    greedily into plain values to be tied by the caller. Non-dyadic lengths
    (tuplet notes) are not representable and return None.
    """
    if value <= 0:
        return None
    for base in _PLAIN:
        if value == Fraction(1, base):
            return [str(base)]
        if value == Fraction(3, 2 * base):
            return [f"{base}."]
    for base in _PLAIN:
        plain = Fraction(1, base)
        if plain < value:
            rest = _tokens(value - plain)
            return None if rest is None else [str(base), *rest]
    return None


def rebar_events(
    events: list[NoteEvent], meter: MeterSpec, *, prefer_flats: bool
) -> str | None:
    """The events as LilyPond in `meter`, barlines and ties where they fall.

    Events must be a monophonic line starting at onset 0 of the entry (the
    caller normalizes); gaps become rests. Returns None when any duration is
    untokenizable (tuplets) or the line overlaps itself — the caller falls
    back to instruction text.

    The final bar is left open when the entry ends mid-bar: the composer
    completes it. Nothing is ever padded (docs/02).
    """
    bar = meter.bar_length
    words: list[str] = []
    cursor = Fraction(0)

    def emit(length: Fraction, render: str | None) -> bool:
        """Advance `cursor` by `length`, splitting at barlines; `render` is
        the pitch text for a note (tied across splits) or None for a rest."""
        nonlocal cursor
        remaining = length
        while remaining > 0:
            to_barline = bar - (cursor % bar)
            piece = min(remaining, to_barline)
            tokens = _tokens(piece)
            if tokens is None:
                return False
            for index, token in enumerate(tokens):
                is_final = remaining == piece and index == len(tokens) - 1
                if render is None:
                    words.append(f"r{token}")
                else:
                    words.append(f"{render}{token}" + ("" if is_final else "~"))
            cursor += piece
            remaining -= piece
            if cursor % bar == 0:
                words.append("|")
        return True

    for event in sorted(events, key=lambda note: note.onset):
        if event.onset < cursor:
            return None  # overlapping line: not a single voice
        if event.onset > cursor:
            if not emit(event.onset - cursor, None):
                return None
        pitch = Pitch.from_midi_number(event.midi_pitch, prefer_flats=prefer_flats)
        if not emit(event.duration, pitch.to_lilypond()):
            return None

    return " ".join(words)
