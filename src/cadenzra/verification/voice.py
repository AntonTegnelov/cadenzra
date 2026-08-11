"""`validate_voice` — the per-fragment gate, run while the blast radius is one voice.

Every check here is decidable, so its verdict is final (docs/05). They run
cheapest-first: a token scan before a compile, a compile before MIDI analysis,
because a fragment that fails the scan has nothing worth compiling.

Messages are authored like rehearsal notes. That is a design requirement, not a
nicety: their real consumer is a regeneration prompt, so "bar 7 does not fill
7/8 (2+2+3); it is off by 1/8" is actionable where "bar check failed" is not
(docs/04, docs/05).
"""

import re
from fractions import Fraction
from pathlib import Path
from typing import Final

import mido

from cadenzra.common.errors import LilypondCompileError
from cadenzra.interfaces.rendering import ScoreRenderer
from cadenzra.model.artifacts import BarCheckWarning
from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.primitives.meter import MeterSpec
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.primitives.time import bar_containing, offset_of
from cadenzra.model.spec import VoiceSpec
from cadenzra.model.structure import SectionPlan
from cadenzra.model.voice import VoicePart
from cadenzra.notation.keys import prefer_flats
from cadenzra.notation.scaffold import (
    ScaffoldedSource,
    bar_of_fragment_position,
    count_bar_checks,
    scaffold_bar_probe,
    scaffold_fragment,
)
from cadenzra.rendering.lilypond import first_error
from cadenzra.verification.lyrics import lyric_misalignment
from cadenzra.verification.midi_analysis import NoteEvent, extract_voice_notes

SOURCE: Final = "validate_voice"

# Structural commands belong to the assembler; a fragment carrying its own is
# no longer a pure music expression and cannot be assembled deterministically
# (docs/03). A denylist is not a parser — which is exactly why this one regex
# is allowed to touch LilyPond text (docs/05).
FORBIDDEN_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        "score",
        "layout",
        "midi",
        "header",
        "time",
        "timeAbbrev",
        "compoundMeter",
        "tempo",
        "clef",
        "key",
        "relative",
        "new",
        "context",
        "version",
    }
)
_COMMAND = re.compile(r"\\(?P<name>[A-Za-z]+)")



def validate_voice(
    part: VoicePart,
    voice_spec: VoiceSpec,
    section: SectionPlan,
    renderer: ScoreRenderer,
    workdir: Path,
) -> list[FeedbackItem]:
    """Check one fragment. An empty list means it is accepted."""
    structural = _check_no_structural_commands(part, section)
    if structural:
        # A fragment carrying \score or \time will not compile inside a
        # scaffold that already provides them. Reporting the cause beats
        # reporting the baffling compiler error it would produce.
        return structural

    scaffolded = scaffold_fragment(
        part.lily_music,
        section.meter,
        clef=_clef_for(voice_spec),
        lily_lyrics=part.lily_lyrics,
        tempo_bpm=section.tempo_bpm,
    )
    try:
        result = renderer.compile(scaffolded.source, workdir)
    except LilypondCompileError as error:
        return [
            _item(
                part,
                section,
                message=(
                    f"the {part.voice_id} part for section {part.section_id} does not "
                    "compile: "
                    + (first_error(error.output) or "the compiler rejected it")
                    + ". Write plain LilyPond: absolute pitch with Dutch note names "
                    "— a flat adds -es and a sharp adds -is on every letter "
                    "(ces des ees fes ges aes bes, cis dis eis fis gis ais bis), "
                    "never cb or eb or f#. An explicit duration on every "
                    "note, and a bar check | at every barline"
                ),
                evidence=error.output,
            )
        ]

    feedback = [
        *_check_bar_checks_present(part, section),
        *_check_bars_fill_the_meter(
            part, section, scaffolded, result.bar_check_warnings, renderer, workdir
        ),
        *_check_lyrics_align(part, section, result.raw_output),
        *_check_techniques(part, section),
    ]
    if result.midi_path is not None:
        feedback += _check_range(part, voice_spec, section, result.midi_path)
    return feedback


def part_events(
    part: VoicePart,
    voice_spec: VoiceSpec,
    section: SectionPlan,
    renderer: ScoreRenderer,
    workdir: Path,
) -> list[NoteEvent]:
    """The compiled notes of an already-validated part.

    The input to the cross-voice checks run at the voice layer. Follows
    `_check_range`'s convention for a renderer that produces no MIDI (the
    scripted test fake): no notes, no MIDI-based judgment.
    """
    scaffolded = scaffold_fragment(
        part.lily_music,
        section.meter,
        clef=_clef_for(voice_spec),
        tempo_bpm=section.tempo_bpm,
    )
    result = renderer.compile(scaffolded.source, workdir)
    if result.midi_path is None:
        return []
    by_track = extract_voice_notes(mido.MidiFile(result.midi_path))
    return [note for notes in by_track.values() for note in notes]


def _check_no_structural_commands(
    part: VoicePart, section: SectionPlan
) -> list[FeedbackItem]:
    feedback = []
    for match in _COMMAND.finditer(part.lily_music):
        if match["name"] not in FORBIDDEN_COMMANDS:
            continue
        line, column = _line_and_column(part.lily_music, match.start())
        bar = bar_of_fragment_position(part.lily_music, line, column)
        feedback.append(
            _item(
                part,
                section,
                bar=bar,
                message=(
                    f"bar {bar} uses \\{match['name']}, which belongs to the score "
                    "rather than to a part; write only notes, rests, durations, "
                    "dynamics and markup, with a bar check at every barline"
                ),
                evidence=match.group(0),
            )
        )
    return feedback


def _check_bar_checks_present(
    part: VoicePart, section: SectionPlan
) -> list[FeedbackItem]:
    """The fragment must carry one bar check per bar of its section.

    The compiler can only report a bar that does not fill if a bar check asks
    it to, so a missing check is not a cosmetic lapse — it is a hole in the
    meter validator itself. Counting is a token scan, not a parser (docs/03).
    """
    found = count_bar_checks(part.lily_music)
    if found == section.bars:
        return []
    return [
        _item(
            part,
            section,
            message=(
                f"the part has {found} bar check{'' if found == 1 else 's'} but section "
                f"{section.section_id} is {section.bars} bars long; write a | at every "
                "barline so each bar can be checked against "
                f"{section.meter.surface_string()}"
            ),
        )
    ]


def _check_bars_fill_the_meter(
    part: VoicePart,
    section: SectionPlan,
    scaffolded: ScaffoldedSource,
    warnings: list[BarCheckWarning],
    renderer: ScoreRenderer,
    workdir: Path,
) -> list[FeedbackItem]:
    """Turn the compiler's bar checks into rehearsal notes.

    The compiler does the duration arithmetic; this only says where, and by how
    much (docs/03). A failed bar check desynchronizes the compiler's measure
    position, so the single compile reports only the first of a run of broken
    bars — a live part with twelve identical overfull bars was taught about
    them one attempt at a time. When any check fails, each bar is recompiled
    as its own score so every broken bar is named at once; where the probe
    cannot represent or confirm the fragment, this compile's report stands.
    """
    if not warnings:
        return []
    probed = _probed_bar_faults(part, section, renderer, workdir)
    if probed is not None:
        return probed
    feedback = []
    for warning in warnings:
        line = scaffolded.fragment_line_of(warning.line)
        bar = bar_of_fragment_position(part.lily_music, line, warning.column)
        feedback.append(
            _bar_fill_item(part, section, bar=bar, warning=warning)
        )
    return feedback


def _probed_bar_faults(
    part: VoicePart,
    section: SectionPlan,
    renderer: ScoreRenderer,
    workdir: Path,
) -> list[FeedbackItem] | None:
    """Every broken bar, from a per-bar recompile — None where unconfirmed.

    None means "keep the single compile's report": the probe declined the
    fragment, a bar could not compile standing alone (cut mid-tuplet), or
    the probe's warnings did not line up with its own scores. All of those
    are external-compiler territory, and the degraded report is the same
    first-broken-bar answer the validator gave before the probe existed.
    """
    probe = scaffold_bar_probe(part.lily_music, section.meter)
    if probe is None:
        return None
    try:
        result = renderer.compile(probe.source, workdir / "bars")
    except LilypondCompileError:
        return None
    feedback = []
    seen: set[int] = set()
    for warning in result.bar_check_warnings:
        bar = probe.bar_of_line.get(warning.line)
        if bar is None:
            return None
        if bar in seen:
            continue
        seen.add(bar)
        feedback.append(_bar_fill_item(part, section, bar=bar, warning=warning))
    return feedback or None


def _bar_fill_item(
    part: VoicePart,
    section: SectionPlan,
    *,
    bar: int,
    warning: BarCheckWarning,
) -> FeedbackItem:
    deficit = deficit_text(warning.message, section.meter)
    return _item(
        part,
        section,
        bar=bar,
        message=(
            f"bar {bar} does not fill {section.meter.surface_string()}"
            + (f"; it is {deficit}" if deficit else "")
            + " — adjust the durations or retie across the barline"
        ),
        evidence=warning.message,
    )


def overflow_of(message: str) -> str | None:
    """The "failed at: 1/8" remainder — where the check landed within the bar."""
    _, marker, remainder = message.partition("failed at:")
    return remainder.strip() if marker else None


def deficit_text(message: str, meter: MeterSpec) -> str | None:
    """The compiler's "failed at: X" turned into the amount a repair needs.

    X is the bar's *content* (mod one bar), not what is missing: a hook
    holding 1/8 in 4/4 fails "at: 1/8", and reporting that as "off by 1/8"
    when the bar is 7/8 short sent repairs across two model tiers hunting
    the wrong number. The warning alone cannot distinguish a bar short by
    (bar − X) from one over by X, so the smaller correction leads and the
    other stays visible — a bar that misses by a sixteenth is overwhelmingly
    one written a sixteenth over, not one nearly empty, and a repair makes
    one small edit toward the number it reads first.
    """
    remainder = overflow_of(message)
    if remainder is None:
        return None
    try:
        position = Fraction(remainder)
    except (ValueError, ZeroDivisionError):
        return None
    missing = meter.bar_length - position
    if position < missing:
        return f"{position} over (or {missing} short)"
    return f"{missing} short (or {position} over)"


def _check_range(
    part: VoicePart, voice_spec: VoiceSpec, section: SectionPlan, midi_path: Path
) -> list[FeedbackItem]:
    """Every note inside the voice's range — a hard constraint (docs/03).

    One item per (bar, side): a bar of stratospheric figuration is one
    rehearsal note naming its extent, not one complaint per note. The
    regeneration prompt is the message's real consumer (docs/05), and a
    flood of eighty identical items teaches it nothing a summary would not.
    """
    offenders: dict[tuple[int, bool], list[Pitch]] = {}
    for notes in extract_voice_notes(mido.MidiFile(midi_path)).values():
        for note in notes:
            pitch = Pitch.from_midi_number(
                note.midi_pitch, prefer_flats=prefer_flats(section.key)
            )
            if pitch.is_within(voice_spec.range_low, voice_spec.range_high):
                continue
            bar = bar_containing(note.onset, section.meter)
            above = pitch.cents > voice_spec.range_high.cents
            offenders.setdefault((bar, above), []).append(pitch)

    feedback = []
    for (bar, above), pitches in sorted(offenders.items()):
        limit = voice_spec.range_high if above else voice_spec.range_low
        # Both spellings, like `range_text`: told only "the ceiling of C5",
        # the live smoke's alto respelled Db5 as cis'' — a note that *reads*
        # like a C — and walked its violations down one semitone per attempt.
        side = f"the {part.voice_id} {'ceiling' if above else 'floor'} of "
        side += f"{limit.to_scientific()} ({limit.to_lilypond()})"
        remedy = _octave_remedy(pitches, voice_spec, above, section)
        if len(pitches) == 1:
            pitch = pitches[0]
            message = (
                f"{pitch.to_scientific()} ({pitch.to_lilypond()}) in bar {bar} "
                f"is {'above' if above else 'below'} {side}{remedy}"
            )
        else:
            extreme = max(pitches, key=lambda p: p.cents if above else -p.cents)
            message = (
                f"bar {bar} has {len(pitches)} notes "
                f"{'above' if above else 'below'} {side}, "
                f"the {'highest' if above else 'lowest'} "
                f"{extreme.to_scientific()} ({extreme.to_lilypond()}){remedy}"
            )
        feedback.append(_item(part, section, bar=bar, message=message))
    return feedback


def _octave_remedy(
    pitches: list[Pitch], voice_spec: VoiceSpec, above: bool, section: SectionPlan
) -> str:
    """The one-edit fix, when it exists: the same notes an octave over.

    Range arithmetic the checker can do exactly, handed over rather than left
    as a puzzle (docs/08 principle 2) — the same reasoning as naming "r16"
    in a deficit. Empty when the shifted notes still miss the range; the
    motif-time octave-fit check makes that rare for prescribed material, and
    a free line that wide has no one-edit answer to name.
    """
    shifted = [
        Pitch.from_midi_number(
            pitch.midi_number + (-12 if above else 12),
            prefer_flats=prefer_flats(section.key),
        )
        for pitch in pitches
    ]
    if not all(
        pitch.is_within(voice_spec.range_low, voice_spec.range_high)
        for pitch in shifted
    ):
        return ""
    direction = "down" if above else "up"
    if len(shifted) == 1:
        fix = shifted[0]
        return (
            f" — the same note an octave {direction}, "
            f"{fix.to_scientific()} ({fix.to_lilypond()}), is in range"
        )
    return (
        f" — the same notes an octave {direction} keep the contour and fit"
    )


def _check_lyrics_align(
    part: VoicePart, section: SectionPlan, compiler_output: str
) -> list[FeedbackItem]:
    """Syllable/note mismatches surface as compiler warnings (docs/05).

    Words are normally written by the lyric layer, which runs this same check
    against its own artifact (docs/10). This stays because a part may still
    arrive carrying lyrics, and the compiler's answer is the same either way.
    """
    if part.lily_lyrics is None or not lyric_misalignment(compiler_output):
        return []
    return [
        _item(
            part,
            section,
            message=(
                f"the lyrics for {part.voice_id} do not line up with its notes; "
                "check syllable hyphens (--) and melisma extenders (__)"
            ),
            evidence=compiler_output,
        )
    ]


def _check_techniques(part: VoicePart, section: SectionPlan) -> list[FeedbackItem]:
    """Technique spans must land inside the section they annotate.

    The vocabulary itself is enforced by `TechniqueSpan`, so only the bar
    bounds are checked here — re-checking what the type system guarantees is
    theater (docs/08, principle 3).
    """
    feedback = []
    for span in part.techniques:
        last_bar = span.to_bar if span.to_bar is not None else span.from_bar
        if last_bar <= section.bars:
            continue
        feedback.append(
            _item(
                part,
                section,
                bar=span.from_bar,
                message=(
                    f"the {span.technique!r} marking runs to bar {last_bar}, but "
                    f"section {section.section_id} is {section.bars} bars long"
                ),
            )
        )
    return feedback


def _clef_for(voice_spec: VoiceSpec) -> str:
    """A clef that keeps the voice on the staff — for the scaffold only.

    The real score's clefs come from the assembler; this just keeps ledger
    lines out of a throwaway compile.
    """
    if voice_spec.range_low.cents < Pitch(step="C", octave=3).cents:
        return "bass"
    if voice_spec.range_low.cents < Pitch(step="C", octave=4).cents:
        return '"treble_8"'
    return "treble"


def _line_and_column(text: str, index: int) -> tuple[int, int]:
    """1-based line and column of a character offset, as LilyPond reports them."""
    line = text.count("\n", 0, index) + 1
    line_start = text.rfind("\n", 0, index) + 1
    return line, index - line_start + 1


def _item(
    part: VoicePart,
    section: SectionPlan,
    *,
    message: str,
    bar: int | None = None,
    evidence: str | None = None,
) -> FeedbackItem:
    location: Fraction | None = None
    if bar is not None:
        location = offset_of(bar, 1, section.meter)
    return FeedbackItem(
        source=SOURCE,
        level="voice",
        section_id=part.section_id,
        voice_id=part.voice_id,
        location=location,
        message=message,
        evidence=evidence,
    )
