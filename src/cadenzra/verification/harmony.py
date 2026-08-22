"""`validate_harmony` — the cheapest, most decidable check in the system.

A skeleton is ordered, gapless, and exactly fills its section, or it is not a
skeleton. All of that is exact `Fraction` arithmetic caught before any notation
exists — floats would mis-sum a page of 7/8 bars and the error would only
surface as a mysterious bar-check failure three layers later (docs/03,
docs/08 principle 3).
"""

from fractions import Fraction
from typing import Final

from cadenzra.model.contexts import PinnedTone
from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.harmony import HarmonicSkeleton
from cadenzra.model.primitives.ids import MotifId
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.primitives.time import format_bar_beat, offset_of, section_length
from cadenzra.model.structure import SectionPlan
from cadenzra.notation.chords import (
    ChordSymbolError,
    known_chord_qualities,
    parse_chord_symbol,
)
from cadenzra.notation.keys import prefer_flats
from cadenzra.verification.midi_analysis import NoteEvent
from cadenzra.verification.section import (
    SUSTAINED_SHARE,
    is_strict,
    permitted_pitch_classes,
)
from cadenzra.verification.transposition import (
    UnknownRelationError,
    parse_relation,
    transpose_semitones,
)

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
    previous = None
    for event in sorted(skeleton.events, key=lambda item: item.offset):
        if event.offset > cursor:
            # A gap flags no chord, and the retry prompt tells the model to
            # change only flagged chords — live, a grid missing one beat
            # came back verbatim six times. The gap names its own edit.
            beat = section.meter.bar_length / section.meter.units_per_bar
            if previous is not None:
                # Absolute target, not a relative "extend by N": told to
                # extend by 1 beat, a live model answered its old duration
                # five identical times — it may well believe the old value
                # already is the extended one. Both numbers close the door.
                target = (event.offset - previous.offset) / beat
                has = (cursor - previous.offset) / beat
                fix = (
                    f"; give the {previous.chord} at "
                    f"{format_bar_beat(previous.offset, section.meter)} a "
                    f"duration of {target} beats (it has {has})"
                )
            else:
                fix = "; start the first chord at bar 1, beat 1"
            feedback.append(
                _item(
                    section,
                    location=cursor,
                    message=(
                        f"nothing is harmonized between "
                        f"{format_bar_beat(cursor, section.meter)} and "
                        f"{format_bar_beat(event.offset, section.meter)}; the "
                        "progression must be gapless"
                        + fix
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
        if previous is None or event.end > previous.end:
            previous = event
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
                        "symbol the system reads; use forms like Dm, Esus4, F#m7, "
                        "Bb/D — a root, one quality from "
                        f"[{known_chord_qualities()}], optional alterations like "
                        "b9/#11 in parentheses, and an optional /bass"
                    ),
                    evidence=str(error),
                )
            )
    return feedback


def check_entries_against_grid(
    skeleton: HarmonicSkeleton,
    section: SectionPlan,
    motif_notes: dict[MotifId, list[NoteEvent]],
    dissonance_policy: str = "",
) -> list[FeedbackItem]:
    """The plan's own consistency: every declared entry against the grid.

    A subject prescribed at a bar cannot change; a grid clashing with it there
    is a contradiction only the grid can resolve — detected downstream, it is
    an unfixable voice-level violation that once survived three repair sweeps
    (the double-fugue's immortal D#4). Deterministic, no LLM: predict each
    entry's sounding pitches and apply exactly the held-tone test the section
    check applies, so a pass here guarantees no unfixable held-tone there.
    Tonal answers are pinned at the literal fifth — that is what the
    prescription hands the voice to copy.
    """
    strict = is_strict(dissonance_policy)
    flats = prefer_flats(section.key)
    beat = section.meter.bar_length / section.meter.units_per_bar
    # Every note the entries hold through each chord slot, gathered first:
    # one failing slot is one item naming the whole requirement set. Two
    # simultaneous subjects once pinned A and Ab through one slot, and six
    # grids satisfied each single-note complaint by breaking the other.
    held: dict[int, list[tuple[str, Pitch]]] = {}
    for entry in section.material:
        subject = motif_notes.get(entry.motif_id)
        if not subject:
            continue
        try:
            relation = parse_relation(entry.relation)
        except UnknownRelationError:
            continue  # the structure validator owns unknown relations
        predicted = predicted_entry(subject, relation.kind, relation.semitones)
        if predicted is None:
            continue
        shift = offset_of(entry.bar, 1, section.meter) - subject[0].onset
        for note in predicted:
            onset = note.onset + shift
            for index, event in enumerate(skeleton.events):
                if not (event.offset < onset + note.duration and onset < event.end):
                    continue
                sounding = min(onset + note.duration, event.end) - max(
                    onset, event.offset
                )
                # Same definition of "held" as the section check: a share of
                # the chord AND at least a beat — a pass here must guarantee
                # no held-tone there, no more and no less.
                if sounding < max(event.duration * SUSTAINED_SHARE, beat):
                    continue
                pitch = Pitch.from_midi_number(note.midi_pitch, prefer_flats=flats)
                slot = held.setdefault(index, [])
                if (entry.voice_id, pitch) not in slot:
                    slot.append((entry.voice_id, pitch))

    feedback = []
    for index, requirements in sorted(held.items()):
        event = skeleton.events[index]
        try:
            chord = parse_chord_symbol(event.chord)
        except ChordSymbolError:
            continue  # _check_symbols owns unreadable chords
        permitted = permitted_pitch_classes(chord, strict)
        missing = [
            (voice, pitch)
            for voice, pitch in requirements
            if pitch.pc12 not in permitted
        ]
        if not missing:
            continue
        examples = chords_containing(
            {pitch.pc12 for _, pitch in requirements}, flats
        )
        message = (
            f"the entries hold {_tone_names(missing)} through "
            f"{format_bar_beat(event.offset, section.meter)}, where the grid "
            f"declares {event.chord}; the chord there must contain "
            f"{_tone_names(requirements)} — the subjects cannot change"
        )
        if examples:
            message += f"; chords that do: {', '.join(examples)} — pick what fits the key"
        feedback.append(
            _item(
                section, location=event.offset, kind="entry_vs_grid", message=message
            )
        )
    return feedback


def _tone_names(tones: list[tuple[str, Pitch]]) -> str:
    return ", ".join(
        f"{pitch.to_scientific()} ({pitch.to_lilypond()}, {voice})"
        for voice, pitch in tones
    )


# Roots and qualities the example search draws on — every symbol here parses,
# so whatever it suggests passes this same check by construction. Simple
# qualities first: the first hit is the plainest chord that works.
_EXAMPLE_QUALITIES: Final = (
    "",
    "m",
    "7",
    "m7",
    "maj7",
    "m6",
    "m7b5",
    "dim7",
    "sus4",
    "7b9",
    "7#9",
)
_ROOTS_SHARP: Final = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_ROOTS_FLAT: Final = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")


def chords_containing(pcs: set[int], flats: bool) -> list[str]:
    """A few chord symbols holding every pc in `pcs` as real chord tones.

    Arithmetic over the checker's own vocabulary — every suggestion passes
    this same check by construction, handed over instead of left as a
    puzzle. The search is strict on purpose: liberal mode would let a plain
    triad "cover" a semitone pair through passing-tone allowances, and a
    chord that merely tolerates the subjects is not an answer. Several are
    named because the search cannot know the key's idiom — one live grid
    refused an Ab at a cadence six times when the equally valid Cm was the
    tonic it wanted all along.
    """
    found: list[str] = []
    for quality in _EXAMPLE_QUALITIES:
        for root in _ROOTS_FLAT if flats else _ROOTS_SHARP:
            try:
                chord = parse_chord_symbol(f"{root}{quality}")
            except ChordSymbolError:
                continue
            if pcs <= permitted_pitch_classes(chord, strict=True):
                found.append(f"{root}{quality}")
                if len(found) == 4:
                    return found
                break  # one root per quality keeps the list varied
    return found


def pinned_entry_tones(
    section: SectionPlan, motif_notes: dict[MotifId, list[NoteEvent]]
) -> list[PinnedTone]:
    """Every entry note long enough to pin the grid, realized and placed.

    Handed to the harmony prompt before the first attempt, because the model
    cannot satisfy constraints it cannot see — discovered through violations,
    a fugue exposition's pinned tones are fixed one at a time while another
    breaks (docs/08 principle 2: hand over the answer, not the puzzle).
    Notes shorter than a beat are left free; they read as passing tones, and
    the held-tone check rarely reaches them.
    """
    beat = section.meter.bar_length / section.meter.units_per_bar
    pinned = []
    for entry in section.material:
        subject = motif_notes.get(entry.motif_id)
        if not subject:
            continue
        try:
            relation = parse_relation(entry.relation)
        except UnknownRelationError:
            continue  # the structure validator owns unknown relations
        predicted = predicted_entry(subject, relation.kind, relation.semitones)
        if predicted is None:
            continue
        shift = offset_of(entry.bar, 1, section.meter) - subject[0].onset
        pinned += [
            PinnedTone(
                voice_id=entry.voice_id,
                midi_pitch=note.midi_pitch,
                onset=note.onset + shift,
                duration=note.duration,
            )
            for note in predicted
            if note.duration >= beat
        ]
    return pinned


def predicted_entry(
    subject: list[NoteEvent], kind: str, semitones: int
) -> list[NoteEvent] | None:
    """The entry's sounding notes, as the prescription will realize them.

    A tonal answer is the literal real answer — a fifth up — because that is
    the text the voice is told to copy; the adjust-a-few-notes license can
    shift a passing degree, and the regrid path still covers that rare case.
    """
    if kind == "exact":
        return subject
    if kind == "transposition":
        return transpose_semitones(subject, semitones)
    if kind == "tonal answer":
        return transpose_semitones(subject, 7)
    if kind == "inversion":
        first = subject[0].midi_pitch
        return [
            note.model_copy(update={"midi_pitch": 2 * first - note.midi_pitch})
            for note in subject
        ]
    return None


def _item(
    section: SectionPlan,
    *,
    message: str,
    location: Fraction | None = None,
    evidence: str | None = None,
    kind: str | None = None,
) -> FeedbackItem:
    return FeedbackItem(
        source=SOURCE,
        level="harmony",
        section_id=section.section_id,
        location=location,
        message=message,
        evidence=evidence,
        kind=kind,
    )
