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
from cadenzra.notation.keys import prefer_flats
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
SUSTAINED_SHARE: Final = Fraction(1, 2)

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
    spans = entry_spans(section, motif_notes or {})
    return [
        *_check_parallels(voices, section, style.parallel_fifths_policy, spans),
        *_check_harmonic_alignment(
            voices, section, skeleton, style.dissonance_policy, spans
        ),
        *_check_material_entries(voices, section, motif_notes or {}),
    ]


def entry_spans(
    section: SectionPlan, motif_notes: dict[MotifId, list[NoteEvent]]
) -> dict[VoiceId, list[tuple[Fraction, Fraction]]]:
    """Where each voice is playing prescribed material, as offset spans.

    A declared entry pins its bars note-for-note, so no repair may ask the
    voice to move there — the router steers pair violations to the *other*
    voice, and a clash wholly inside prescribed spans escalates instead. The
    span is the motif's own length from the entry bar: a lower bound under
    augmentation, which errs toward treating a voice as free — the failure
    mode that stays repairable.
    """
    spans: dict[VoiceId, list[tuple[Fraction, Fraction]]] = {}
    for entry in section.material:
        subject = motif_notes.get(entry.motif_id)
        if not subject:
            continue
        start = offset_of(entry.bar, 1, section.meter)
        length = subject[-1].end - subject[0].onset
        spans.setdefault(entry.voice_id, []).append((start, start + length))
    return spans


def _prescribed(
    spans: dict[VoiceId, list[tuple[Fraction, Fraction]]],
    voice_id: VoiceId,
    start: Fraction,
    end: Fraction,
) -> bool:
    """Whether [start, end] touches any of the voice's prescribed spans."""
    return any(
        span_start <= end and start < span_end
        for span_start, span_end in spans.get(voice_id, [])
    )


def _check_parallels(
    voices: dict[VoiceId, list[NoteEvent]],
    section: SectionPlan,
    policy: ParallelsPolicy,
    spans: dict[VoiceId, list[tuple[Fraction, Fraction]]],
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
            for interval, onsets in parallel_runs(voices[upper], voices[lower]):
                feedback += _routed_pair_items(
                    upper, lower, interval, onsets, section, spans
                )
    return feedback


def parallel_runs(
    upper: list[NoteEvent], lower: list[NoteEvent]
) -> list[tuple[str, list[Fraction]]]:
    """Maximal passages of parallel motion, as (interval, onsets) runs.

    One passage is one fault. The old per-attack accounting turned a five-note
    parallel run into four violations, which is how a repair prompt ends up
    carrying 45 complaints for nine problems (the cost audit measured 207
    events collapsing to ~44 passages).
    """
    pairs = _simultaneous_pairs(upper, lower)
    runs: list[tuple[str, list[Fraction]]] = []
    current: list[Fraction] = []
    current_interval = ""
    previous_index = -2
    for index, ((first_up, first_down), (next_up, next_down)) in enumerate(
        zip(pairs, pairs[1:], strict=False)
    ):
        first = abs(first_up.midi_pitch - first_down.midi_pitch) % _OCTAVE
        second = abs(next_up.midi_pitch - next_down.midi_pitch) % _OCTAVE
        violating = first == second and first in (0, _PERFECT_FIFTH)
        if violating:
            up_motion = next_up.midi_pitch - first_up.midi_pitch
            down_motion = next_down.midi_pitch - first_down.midi_pitch
            violating = (
                up_motion != 0
                and down_motion != 0
                and (up_motion > 0) == (down_motion > 0)
            )
        if not violating:
            continue
        interval = "octaves" if first == 0 else "fifths"
        if current and index == previous_index + 1 and interval == current_interval:
            current.append(next_up.onset)
        else:
            if current:
                runs.append((current_interval, current))
            current = [next_up.onset]
            current_interval = interval
        previous_index = index
    if current:
        runs.append((current_interval, current))
    return runs


def _routed_pair_items(
    upper_name: VoiceId,
    lower_name: VoiceId,
    interval: str,
    onsets: list[Fraction],
    section: SectionPlan,
    spans: dict[VoiceId, list[tuple[Fraction, Fraction]]],
) -> list[FeedbackItem]:
    """One passage's items, routed to whoever is actually free to move.

    A voice inside a prescribed entry span cannot change without failing the
    entry check — telling it to is how the double-fugue loop oscillated
    between two validators. One voice free: it gets the item. Both free: both
    are told (each sees the other's line on repair). Neither: the item is
    voiceless and `routing="unfixable"` — the plan owns that contradiction,
    and the section loop escalates it rather than spending budget.
    """
    start, end = onsets[0], onsets[-1]
    where = (
        f"into {format_bar_beat(start, section.meter)}"
        if len(onsets) == 1
        else (
            f"from {format_bar_beat(start, section.meter)} through "
            f"{format_bar_beat(end, section.meter)}"
        )
    )
    each = "the second one" if len(onsets) == 1 else "each"
    message = (
        f"{upper_name} and {lower_name} move in parallel {interval} {where}; "
        f"approach {each} by contrary or oblique motion"
    )
    pair = tuple(sorted((upper_name, lower_name)))

    def routed(voice_id: VoiceId | None, routing: str) -> FeedbackItem:
        return _item(
            section,
            voice_id=voice_id,
            routing=routing,
            kind="parallels",
            voices=pair,
            span=(start, end),
            location=start,
            message=message,
        )

    upper_fixed = _prescribed(spans, upper_name, start, end)
    lower_fixed = _prescribed(spans, lower_name, start, end)
    if upper_fixed and lower_fixed:
        return [routed(None, "unfixable")]
    if upper_fixed or lower_fixed:
        return [routed(lower_name if upper_fixed else upper_name, "only-free-voice")]
    return [routed(voice, "both-free") for voice in pair]


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


def permitted_pitch_classes(chord: ParsedChord, strict: bool) -> frozenset[int]:
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


def is_strict(policy: str) -> bool:
    lowered = policy.lower()
    return any(marker in lowered for marker in _STRICT_MARKERS)


def _check_harmonic_alignment(
    voices: dict[VoiceId, list[NoteEvent]],
    section: SectionPlan,
    skeleton: HarmonicSkeleton,
    dissonance_policy: str = "",
    spans: dict[VoiceId, list[tuple[Fraction, Fraction]]] | None = None,
) -> list[FeedbackItem]:
    """Sounding pitches against the chord the skeleton declares.

    Non-chord tones are permitted; the checker looks for pitches that clash
    *and* are held, which is the decidable part of "does the music realize this
    harmony" (docs/05).
    """
    strict = is_strict(dissonance_policy)
    spans = spans or {}
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

        # "Held" needs both: a real share of the chord, and at least a beat
        # of absolute overlap. Without the floor, a finer chord rhythm makes
        # the check stricter — a passing eighth under a beat-long chord was
        # flagged as a held tone, and six grids died looking for a chord
        # containing the melody's neighbours all at once.
        beat = section.meter.bar_length / section.meter.units_per_bar
        threshold = max(event.duration * SUSTAINED_SHARE, beat)
        permitted = permitted_pitch_classes(chord, strict)
        for voice_id, notes in sorted(voices.items()):
            for note in notes_sounding_at(notes, event.offset):
                pitch = Pitch.from_midi_number(
                    note.midi_pitch, prefer_flats=prefer_flats(section.key)
                )
                if pitch.pc12 in permitted:
                    continue
                sounding = min(note.end, event.end) - max(note.onset, event.offset)
                if sounding < threshold:
                    continue
                # A held clash inside the voice's own prescribed entry is the
                # subject clashing with the grid — the plan's contradiction,
                # unfixable by the voice, so it carries no routed target.
                pinned = _prescribed(spans, voice_id, note.onset, note.end)
                feedback.append(
                    _item(
                        section,
                        voice_id=None if pinned else voice_id,
                        location=note.onset,
                        kind="held_tone",
                        voices=(voice_id,),
                        routing="unfixable" if pinned else None,
                        message=(
                            f"{voice_id} holds {pitch.to_scientific()} "
                            f"({pitch.to_lilypond()}) through "
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
                    kind="entry",
                    voices=(entry.voice_id,),
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
                    kind="entry",
                    voices=(entry.voice_id,),
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
                    kind="entry",
                    voices=(entry.voice_id,),
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
                    kind="entry",
                    voices=(entry.voice_id,),
                    location=start,
                    message=(
                        f"the {entry.voice_id} entry at bar {entry.bar} has the right "
                        f"notes for {entry.motif_id} but not its rhythm: it needs the "
                        f"durations {_durations_text(subject)}, and has "
                        f"{_durations_text(candidate)}"
                    ),
                )
            )
    return feedback


def _durations_text(notes: list[NoteEvent]) -> str:
    """Note values as a musician writes them, so feedback names the rhythm.

    "Not its rhythm" is not actionable; "it needs 8 8 8 4. and has 4 4 8 8" is.
    Same reasoning as naming the target pitch of a transposed entry rather than
    asking the model to work it out.
    """
    return " ".join(_duration_name(note.duration) for note in notes) or "(nothing)"


def _duration_name(duration: Fraction) -> str:
    """A whole-note fraction as LilyPond spells it: 1, 2, 4., 8, 16."""
    for dots, factor in ((0, Fraction(1)), (1, Fraction(3, 2)), (2, Fraction(7, 4))):
        plain = duration / factor
        if plain.numerator == 1 and _is_power_of_two(plain.denominator):
            return f"{plain.denominator}{'.' * dots}"
    return f"{duration.numerator}/{duration.denominator}"


def _is_power_of_two(value: int) -> bool:
    return value > 0 and not value & (value - 1)


def _item(
    section: SectionPlan,
    *,
    message: str,
    voice_id: VoiceId | None = None,
    location: Fraction | None = None,
    evidence: str | None = None,
    kind: str | None = None,
    voices: tuple[VoiceId, ...] = (),
    span: tuple[Fraction, Fraction] | None = None,
    routing: str | None = None,
) -> FeedbackItem:
    return FeedbackItem(
        source=SOURCE,
        level="section",
        section_id=section.section_id,
        voice_id=voice_id,
        location=location,
        message=message,
        evidence=evidence,
        kind=kind,
        voices=voices,
        span=span,
        routing=routing,
    )


def bar_of(offset: Fraction, meter: MeterSpec) -> int:
    """Re-exported for callers that build their own messages."""
    return bar_containing(offset, meter)
