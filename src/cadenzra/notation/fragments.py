"""Token-level inspection of a fragment.

Same justification as the bar-check counting in `scaffold.py`: reading the
*first pitch token* is a token scan, not a parser, and the system deliberately
never grew a LilyPond parser (docs/05). Nothing here interprets durations,
structure, or anything that the compiler is the authority on.
"""

import re

from cadenzra.model.primitives.pitch import Pitch

# A pitch as the fragment contract writes it: a note letter, an optional
# accidental in LilyPond's Dutch spelling, then octave marks. Longest
# accidentals first so `isis` is never read as `is` plus junk.
_PITCH = re.compile(
    r"(?<![a-z\\])(?P<pitch>[a-g](?:isih|eseh|isis|eses|is|es|ih|eh)?[',]*)(?=[0-9\s.~(\[]|$)"
)


def first_pitch(lily_music: str) -> Pitch | None:
    """The first sounding pitch of a fragment, or None if it has none.

    Returns None rather than raising: a fragment starting with a rest, or one
    the scan simply cannot read, is not an error here — it only means the
    caller has nothing extra to say about it.
    """
    for match in _PITCH.finditer(lily_music):
        try:
            return Pitch.from_lilypond(match["pitch"])
        except ValueError:
            continue
    return None


def transposed_first_pitch(lily_music: str, semitones: int) -> Pitch | None:
    """Where a fragment would start after a transposition.

    This exists so a prompt can name the target pitch outright instead of
    asking the model to work out "a fifth above d'" for itself. The arithmetic
    is ours; the model should be spending its attention on the music (docs/08,
    principle 2).
    """
    pitch = first_pitch(lily_music)
    if pitch is None:
        return None
    try:
        return Pitch.from_midi_number(pitch.midi_number + semitones)
    except ValueError:
        return None
