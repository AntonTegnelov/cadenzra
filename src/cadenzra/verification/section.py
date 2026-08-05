"""`validate_section` — the checks that only exist between voices.

Everything here needs more than one line to be true or false: parallels, voice
crossing, whether the sounding harmony matches the skeleton, and whether a
declared motif entry actually is the motif (docs/05).

It is pure over already-compiled MIDI. The compile happens in the node above,
so this module has no services and no I/O — values in, feedback out.
"""

from fractions import Fraction
from typing import Final

from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.harmony import HarmonicSkeleton
from cadenzra.model.primitives.ids import MotifId, VoiceId
from cadenzra.model.primitives.meter import MeterSpec
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.primitives.time import bar_containing, format_bar_beat, offset_of
from cadenzra.model.structure import SectionPlan
from cadenzra.model.style import ParallelsPolicy, StylePack
from cadenzra.notation.chords import (
    ChordSymbolError,
    ParsedChord,
    parse_chord_symbol,
)
from cadenzra.verification.midi_analysis import (
    TICK_TOLERANCE,
    NoteEvent,
    notes_sounding_at,
    within_tolerance,
)
from cadenzra.verification.transposition import (
    UnknownRelationError,
    intervals_match_under_relation,
    parse_relation,
    rhythm_profile_matches,
)

SOURCE: Final = "validate_section"

_PERFECT_FIFTH: Final = 7
_OCTAVE: Final = 12

# A non-chord tone is unremarkable in passing and conspicuous when held. The
# checker flags only *sustained* unexplained clashes (docs/05); this is the
# line between the two, as a share of the harmonic event it sits in.
_SUSTAINED_SHARE: Final = Fraction(1, 2)

# Upper extensions above the root: ninths, elevenths and thirteenths, altered
# and unaltered. A held A over a G minor chord is a ninth, not a wrong note.
#
# The width of this set is a deliberate position, not laziness. docs/01 lists
# "a general music-theory engine" as a non-goal — validators check specific,
# decidable properties and do not attempt to formalize good music. A narrow
# reading of "non-chord tone" would have this check rejecting ninths, sharp
# elevenths and modal colour, i.e. legislating taste under the cover of
# arithmetic. What stays decidable, and stays worth checking, is whether a
# sustained pitch is explainable by the declared harmony *at all*.
# The ninth, eleventh, sharp eleventh, thirteenth and flat seventh: the tensions
# a working musician adds without anyone calling it a wrong note. What stays
# flagged is the genuinely biting material — a flat ninth, a minor third over a
# major chord, a sharp fifth — held through half a chord.
_EXTENSIONS: Final[tuple[int, ...]] = (2, 5, 6, 9, 10)

# Chords that name no third leave it to the voices: F over D5 is what makes
# the chord minor, not a clash with it.
_THIRDS: Final[tuple[int, ...]] = (3, 4)
_THIRDLESS_QUALITIES: Final[frozenset[str]] = frozenset({"5", "sus", "sus2", "sus4"})

# The word a style pack uses when it wants the strict reading.
_STRICT_MARKERS: Final[tuple[str, ...]] = ("strict", "consonant", "no non-chord")


def validate_section(
    voices: dict[VoiceId, list[NoteEvent]],
    section: SectionPlan,
    skeleton: HarmonicSkeleton,
    style: StylePack,
    motif_notes: dict[MotifId, list[NoteEvent]] | None = None,
) -> list[FeedbackItem]:
    """Check one assembled section. An empty list means it is accepted.

    `motif_notes` carries each motif already compiled and analyzed. Motifs are
    stored as notation, and this module does not compile — the node above owns
    the one compile and hands the notes down, which keeps this function pure.
    """
    return [
        *_check_parallels(voices, section, style.parallel_fifths_policy),
        *_check_harmonic_alignment(voices, section, skeleton, style.dissonance_policy),
        *_check_material_entries(voices, section, motif_notes or {}),
    ]


def _check_parallels(
    voices: dict[VoiceId, list[NoteEvent]],
    section: SectionPlan,
    policy: ParallelsPolicy,
) -> list[FeedbackItem]:
    """Parallel fifths and octaves, judged against the style's policy.

    The same checker forbids them for a chorale and waves them through for a
    rock texture — driven by data, not by a branch per genre (docs/03).
    """
    if policy != "forbid":
        return []

    feedback = []
    names = sorted(voices)
    for upper_index, upper in enumerate(names):
        for lower in names[upper_index + 1 :]:
            feedback += _parallels_between(
                upper, voices[upper], lower, voices[lower], section
            )
    return feedback


def _parallels_between(
    upper_name: VoiceId,
    upper: list[NoteEvent],
    lower_name: VoiceId,
    lower: list[NoteEvent],
    section: SectionPlan,
) -> list[FeedbackItem]:
    """Consecutive perfect intervals reached by similar motion."""
    pairs = _simultaneous_pairs(upper, lower)
    feedback = []
    for (first_up, first_down), (next_up, next_down) in zip(pairs, pairs[1:], strict=False):
        first = abs(first_up.midi_pitch - first_down.midi_pitch) % _OCTAVE
        second = abs(next_up.midi_pitch - next_down.midi_pitch) % _OCTAVE
        if first != second or first not in (0, _PERFECT_FIFTH):
            continue
        up_motion = next_up.midi_pitch - first_up.midi_pitch
        down_motion = next_down.midi_pitch - first_down.midi_pitch
        if up_motion == 0 or down_motion == 0 or (up_motion > 0) != (down_motion > 0):
            continue
        interval = "octaves" if first == 0 else "fifths"
        feedback.append(
            _item(
                section,
                voice_id=upper_name,
                location=next_up.onset,
                message=(
                    f"{upper_name} and {lower_name} move in parallel {interval} into "
                    f"{format_bar_beat(next_up.onset, section.meter)}; approach the "
                    "second one by contrary or oblique motion"
                ),
            )
        )
    return feedback


def _simultaneous_pairs(
    upper: list[NoteEvent], lower: list[NoteEvent]
) -> list[tuple[NoteEvent, NoteEvent]]:
    """Notes the two voices attack together, in time order."""
    pairs = []
    for note in upper:
        for other in lower:
            if within_tolerance(note.onset, other.onset):
                pairs.append((note, other))
                break
    return pairs


def _permitted_pitch_classes(chord: ParsedChord, strict: bool) -> frozenset[int]:
    """What the harmony explains: its own tones, plus upper extensions.

    Extensions are admitted by default because a ninth over a minor triad is
    ordinary colour in most idioms, and a validator that called it a wrong note
    would be enforcing a taste the style never asked for. A style pack that
    says it wants strict consonance gets the narrow reading instead.
    """
    if strict:
        return chord.pitch_classes
    steps = list(_EXTENSIONS)
    if chord.quality in _THIRDLESS_QUALITIES:
        steps += list(_THIRDS)
    return frozenset(chord.pitch_classes) | {
        (chord.root_pc + step) % 12 for step in steps
    }


def _is_strict(policy: str) -> bool:
    lowered = policy.lower()
    return any(marker in lowered for marker in _STRICT_MARKERS)


def _check_harmonic_alignment(
    voices: dict[VoiceId, list[NoteEvent]],
    section: SectionPlan,
    skeleton: HarmonicSkeleton,
    dissonance_policy: str = "",
) -> list[FeedbackItem]:
    """Sounding pitches against the chord the skeleton declares.

    Non-chord tones are permitted; the checker looks for pitches that clash
    *and* are held, which is the decidable part of "does the music realize this
    harmony" (docs/05).
    """
    strict = _is_strict(dissonance_policy)
    feedback = []
    for event in skeleton.events:
        try:
            chord = parse_chord_symbol(event.chord)
        except ChordSymbolError as error:
            feedback.append(
                _item(
                    section,
                    location=event.offset,
                    message=(
                        f"the chord {event.chord!r} at "
                        f"{format_bar_beat(event.offset, section.meter)} is not one the "
                        "harmony checker can read"
                    ),
                    evidence=str(error),
                )
            )
            continue

        threshold = event.duration * _SUSTAINED_SHARE
        permitted = _permitted_pitch_classes(chord, strict)
        for voice_id, notes in sorted(voices.items()):
            for note in notes_sounding_at(notes, event.offset):
                pitch = Pitch.from_midi_number(note.midi_pitch)
                if pitch.pc12 in permitted:
                    continue
                sounding = min(note.end, event.end) - max(note.onset, event.offset)
                if sounding < threshold:
                    continue
                feedback.append(
                    _item(
                        section,
                        voice_id=voice_id,
                        location=note.onset,
                        message=(
                            f"{voice_id} holds {pitch.to_scientific()} through "
                            f"{format_bar_beat(event.offset, section.meter)}, where the "
                            f"harmony is {event.chord}; resolve it by step or make it a "
                            "chord tone"
                        ),
                    )
                )
    return feedback


def _check_material_entries(
    voices: dict[VoiceId, list[NoteEvent]],
    section: SectionPlan,
    motif_notes: dict[MotifId, list[NoteEvent]],
) -> list[FeedbackItem]:
    """Every declared entry must actually realize its motif.

    This is what makes a fugue exposition enforceable rather than merely
    described (docs/03).
    """
    if not section.material:
        return []

    feedback = []
    for entry in section.material:
        if entry.motif_id not in motif_notes:
            feedback.append(
                _item(
                    section,
                    voice_id=entry.voice_id,
                    message=(
                        f"the entry at bar {entry.bar} names {entry.motif_id!r}, which "
                        "is not in the motif library"
                    ),
                )
            )
            continue

        try:
            relation = parse_relation(entry.relation)
        except UnknownRelationError as error:
            feedback.append(
                _item(
                    section,
                    voice_id=entry.voice_id,
                    message=(
                        f"the entry at bar {entry.bar} declares the relation "
                        f"{entry.relation!r}, which is not one the checker knows"
                    ),
                    evidence=str(error),
                )
            )
            continue

        subject = motif_notes[entry.motif_id]
        sung = voices.get(entry.voice_id, [])
        start = offset_of(entry.bar, 1, section.meter)
        # Locate the entry by note *count* rather than by a time window sized
        # from the motif. An entry in augmentation occupies more time than the
        # subject does, and a window would truncate it into a length mismatch —
        # a true-but-misleading diagnosis. Taken this way, the pitch check and
        # the rhythm check each report the thing they actually measure.
        candidate = [note for note in sung if note.onset >= start - TICK_TOLERANCE][
            : len(subject)
        ]

        result = intervals_match_under_relation(subject, candidate, relation)
        if not result.ok:
            where = (
                format_bar_beat(result.first_deviation_offset, section.meter)
                if result.first_deviation_offset is not None
                else f"bar {entry.bar}"
            )
            feedback.append(
                _item(
                    section,
                    voice_id=entry.voice_id,
                    location=result.first_deviation_offset or start,
                    message=(
                        f"the {entry.voice_id} entry at bar {entry.bar} should be "
                        f"{entry.motif_id} ({relation.describe()}), but it departs from "
                        f"the subject at {where}: {result.detail}"
                    ),
                )
            )
        elif not rhythm_profile_matches(subject, candidate):
            feedback.append(
                _item(
                    section,
                    voice_id=entry.voice_id,
                    location=start,
                    message=(
                        f"the {entry.voice_id} entry at bar {entry.bar} has the right "
                        f"notes for {entry.motif_id} but not its rhythm"
                    ),
                )
            )
    return feedback


def _item(
    section: SectionPlan,
    *,
    message: str,
    voice_id: VoiceId | None = None,
    location: Fraction | None = None,
    evidence: str | None = None,
) -> FeedbackItem:
    return FeedbackItem(
        source=SOURCE,
        level="section",
        section_id=section.section_id,
        voice_id=voice_id,
        location=location,
        message=message,
        evidence=evidence,
    )


def bar_of(offset: Fraction, meter: MeterSpec) -> int:
    """Re-exported for callers that build their own messages."""
    return bar_containing(offset, meter)
