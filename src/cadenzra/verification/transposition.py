"""Verifying that declared material actually returns.

A `MaterialEntry` claims that the music at some position realizes a motif under
a named relation. This module decides that claim, which is what turns "themes
that return" from an aspiration into a machine-checked property (docs/03).

Relations split in two. **Exact** transforms — transposition, inversion — leave
the interval sequence rigidly determined, so they check as strict equality
after the transform. A **tonal answer** does not: the idiom adjusts scale
degrees to keep the answer inside the key, which bends individual intervals
while preserving the contour. It therefore checks with a bounded per-interval
deviation, and the bound is anchored to real subject/answer pairs in the
fixtures rather than chosen from intuition (docs/05).
"""

import re
from fractions import Fraction
from typing import Final, Literal

from pydantic import BaseModel

from cadenzra.verification.midi_analysis import NoteEvent, within_tolerance

# The controlled vocabulary. An unrecognized relation is a validator failure,
# never a silent pass — docs/03 lists the examples, this pins the grammar.
_INTERVAL_SEMITONES: Final[dict[str, int]] = {
    "unison": 0,
    "m2": 1,
    "M2": 2,
    "m3": 3,
    "M3": 4,
    "P4": 5,
    "tritone": 6,
    "A4": 6,
    "d5": 6,
    "P5": 7,
    "m6": 8,
    "M6": 9,
    "m7": 10,
    "M7": 11,
    "octave": 12,
    "P8": 12,
}

_TRANSPOSITION = re.compile(
    r"^(?P<interval>[A-Za-z0-9]+)\s+(?P<direction>up|down|above|below)$", re.IGNORECASE
)

type RelationKind = Literal["exact", "transposition", "inversion", "tonal answer"]

# A tonal answer is a transposition with a few notes nudged to stay in the key.
# The bounds are stated per *note*, not per interval, because adjusting one note
# necessarily changes the two intervals around it — counting intervals would
# make a single textbook adjustment look like two deviations.
TONAL_ANSWER_MAX_DEVIATION: Final = 2
TONAL_ANSWER_MAX_ALTERED_SHARE: Final = Fraction(1, 3)


class UnknownRelationError(ValueError):
    """The relation string is not in the controlled vocabulary."""


class Relation(BaseModel, frozen=True):
    """A parsed `MaterialEntry.relation`."""

    kind: RelationKind
    semitones: int = 0
    source: str = ""

    def describe(self) -> str:
        """How a rehearsal note would name it."""
        return self.source or self.kind


class MatchResult(BaseModel, frozen=True):
    """Whether an entry realizes its motif, and where it first stops doing so."""

    ok: bool
    first_deviation_index: int | None = None
    first_deviation_offset: Fraction | None = None
    detail: str = ""


def parse_relation(relation: str) -> Relation:
    """Parse a declared relation, or raise.

    Raising is the point: an unrecognized relation must surface as a structure
    validator failure rather than quietly verifying nothing.
    """
    text = relation.strip()
    lowered = text.lower()

    if lowered in ("exact", "same", "unison"):
        return Relation(kind="exact", semitones=0, source=text)
    if lowered in ("inversion", "inverted"):
        return Relation(kind="inversion", source=text)
    if lowered in ("tonal answer", "tonal", "answer"):
        return Relation(kind="tonal answer", source=text)
    if lowered in ("real answer", "real"):
        # A real answer is a literal transposition to the fifth.
        return Relation(kind="transposition", semitones=7, source=text)

    match = _TRANSPOSITION.match(text)
    if match is not None:
        interval = _lookup_interval(match["interval"])
        if interval is not None:
            sign = -1 if match["direction"].lower() in ("down", "below") else 1
            return Relation(kind="transposition", semitones=sign * interval, source=text)

    raise UnknownRelationError(
        f"{relation!r} is not a known material relation; expected one of "
        "'exact', 'inversion', 'tonal answer', 'real answer', or "
        "'<interval> up|down' (e.g. 'P5 up', 'octave down')"
    )


def _lookup_interval(name: str) -> int | None:
    if name in _INTERVAL_SEMITONES:
        return _INTERVAL_SEMITONES[name]
    for known, semitones in _INTERVAL_SEMITONES.items():
        if known.lower() == name.lower():
            return semitones
    return None


def interval_sequence(notes: list[NoteEvent]) -> list[int]:
    """Successive semitone steps — the shape a transposition leaves untouched."""
    return [
        later.midi_pitch - earlier.midi_pitch
        for earlier, later in zip(notes, notes[1:], strict=False)
    ]


def rhythm_profile(notes: list[NoteEvent]) -> list[Fraction]:
    """Onset-to-onset spacing, relative to the first note."""
    return [
        later.onset - earlier.onset
        for earlier, later in zip(notes, notes[1:], strict=False)
    ]


def rhythm_profile_matches(motif: list[NoteEvent], entry: list[NoteEvent]) -> bool:
    """Whether an entry keeps the motif's rhythm, within tick tolerance."""
    motif_profile, entry_profile = rhythm_profile(motif), rhythm_profile(entry)
    if len(motif_profile) != len(entry_profile):
        return False
    return all(
        within_tolerance(expected, actual)
        for expected, actual in zip(motif_profile, entry_profile, strict=True)
    )


def intervals_match_under_relation(
    motif: list[NoteEvent], entry: list[NoteEvent], relation: Relation
) -> MatchResult:
    """Whether `entry` realizes `motif` under `relation`.

    Reports the *first* deviating position, because that is what a rehearsal
    note needs to name: "the entry at bar 5 should be the subject a fifth up;
    beats 3-4 deviate from its interval sequence" (docs/04).
    """
    if len(motif) < 2:
        return MatchResult(ok=False, detail="a motif needs at least two notes to compare")
    if len(entry) != len(motif):
        return MatchResult(
            ok=False,
            first_deviation_index=min(len(entry), len(motif)),
            first_deviation_offset=entry[-1].onset if entry else None,
            detail=(
                f"the entry has {len(entry)} notes; the motif has {len(motif)}"
            ),
        )

    if relation.kind == "tonal answer":
        return _match_tonal_answer(motif, entry)

    expected = interval_sequence(motif)
    if relation.kind == "inversion":
        expected = [-step for step in expected]
    return _match_exact(expected, interval_sequence(entry), entry)


def _match_exact(
    expected: list[int], actual: list[int], entry: list[NoteEvent]
) -> MatchResult:
    """Transposition and inversion preserve the interval sequence rigidly."""
    for index, (want, got) in enumerate(zip(expected, actual, strict=True)):
        if want != got:
            return MatchResult(
                ok=False,
                first_deviation_index=index + 1,
                first_deviation_offset=entry[index + 1].onset,
                detail=(
                    f"interval {index + 1} is {got} semitones; the motif has {want}"
                ),
            )
    return MatchResult(ok=True)


def _match_tonal_answer(motif: list[NoteEvent], entry: list[NoteEvent]) -> MatchResult:
    """A tonal answer may bend scale degrees but not the contour.

    The entry is measured against the literal transposition implied by its own
    first note. Three things must hold: no note strays more than a step from
    where a real answer would put it, only a minority of notes stray at all —
    a line that adjusts everything is a different subject, not an answer to
    this one — and no interval reverses direction, which a step-sized
    adjustment can still do to a semitone interval.
    """
    offset = entry[0].midi_pitch - motif[0].midi_pitch
    deviations = [
        note.midi_pitch - (reference.midi_pitch + offset)
        for reference, note in zip(motif, entry, strict=True)
    ]

    for index, deviation in enumerate(deviations):
        if abs(deviation) > TONAL_ANSWER_MAX_DEVIATION:
            return MatchResult(
                ok=False,
                first_deviation_index=index,
                first_deviation_offset=entry[index].onset,
                detail=(
                    f"note {index + 1} sits {abs(deviation)} semitones from where the "
                    "subject would put it; a tonal answer adjusts a scale degree, "
                    "not a leap"
                ),
            )

    expected_intervals = interval_sequence(motif)
    actual_intervals = interval_sequence(entry)
    for index, (want, got) in enumerate(
        zip(expected_intervals, actual_intervals, strict=True)
    ):
        if (want > 0) != (got > 0) or (want == 0) != (got == 0):
            return MatchResult(
                ok=False,
                first_deviation_index=index + 1,
                first_deviation_offset=entry[index + 1].onset,
                detail=(
                    f"interval {index + 1} changes direction against the subject; "
                    "a tonal answer preserves contour"
                ),
            )

    altered = sum(1 for deviation in deviations if deviation != 0)
    allowed = max(1, int(len(motif) * TONAL_ANSWER_MAX_ALTERED_SHARE))
    if altered > allowed:
        return MatchResult(
            ok=False,
            first_deviation_index=None,
            detail=(
                f"{altered} of {len(motif)} notes differ from the subject; "
                f"a tonal answer adjusts at most {allowed}"
            ),
        )
    return MatchResult(ok=True)


def transpose_semitones(notes: list[NoteEvent], semitones: int) -> list[NoteEvent]:
    """The motif as it would sound under a transposition — used for range-fit."""
    return [note.model_copy(update={"midi_pitch": note.midi_pitch + semitones}) for note in notes]
