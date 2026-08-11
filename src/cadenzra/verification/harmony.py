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
from cadenzra.model.primitives.ids import MotifId
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.primitives.time import format_bar_beat, offset_of, section_length
from cadenzra.model.structure import SectionPlan
from cadenzra.notation.chords import ChordSymbolError, parse_chord_symbol
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
    feedback = []
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
        start = offset_of(entry.bar, 1, section.meter)
        shift = start - subject[0].onset
        for note in predicted:
            onset = note.onset + shift
            for event in skeleton.events:
                if not (event.offset < onset + note.duration and onset < event.end):
                    continue
                try:
                    chord = parse_chord_symbol(event.chord)
                except ChordSymbolError:
                    continue  # _check_symbols owns unreadable chords
                pitch = Pitch.from_midi_number(
                    note.midi_pitch, prefer_flats=prefer_flats(section.key)
                )
                if pitch.pc12 in permitted_pitch_classes(chord, strict):
                    continue
                sounding = min(onset + note.duration, event.end) - max(onset, event.offset)
                if sounding < event.duration * SUSTAINED_SHARE:
                    continue
                feedback.append(
                    _item(
                        section,
                        location=onset,
                        kind="entry_vs_grid",
                        message=(
                            f"the {entry.voice_id} entry at bar {entry.bar} holds "
                            f"{pitch.to_scientific()} ({pitch.to_lilypond()}) through "
                            f"{format_bar_beat(event.offset, section.meter)}, where the "
                            f"grid declares {event.chord}; choose a chord there that "
                            f"contains {pitch.to_scientific()} — the subject cannot "
                            "change"
                        ),
                    )
                )
    return feedback


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
