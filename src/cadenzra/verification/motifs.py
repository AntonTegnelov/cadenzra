"""`validate_motifs` — the highest-leverage check in the pipeline.

Motifs are the highest-leverage notes in the piece: every declared entry across
the whole work derives from them, so they get both the deterministic treatment
and, elsewhere, an LLM review for memorability (docs/04).

The check that earns its keep here is **range-fit under every declared
relation**. A subject that fits the soprano can leave the alto's fifth-below
answer under its floor; catching that here costs one check, catching it after
the sections are written costs regenerating them (docs/05).
"""

from itertools import combinations
from pathlib import Path
from typing import Final

import mido

from cadenzra.common.errors import LilypondCompileError
from cadenzra.interfaces.rendering import ScoreRenderer
from cadenzra.model.artifacts import BarCheckWarning
from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.motif import Motif, MotifLibrary
from cadenzra.model.primitives.meter import MeterSpec
from cadenzra.model.primitives.time import bar_containing, offset_of
from cadenzra.model.spec import PieceSpec
from cadenzra.model.structure import MaterialEntry, StructurePlan
from cadenzra.notation.rebar import octave_displacement
from cadenzra.notation.scaffold import scaffold_fragment
from cadenzra.rendering.lilypond import first_error
from cadenzra.verification.harmony import predicted_entry
from cadenzra.verification.midi_analysis import NoteEvent, extract_voice_notes
from cadenzra.verification.section import parallel_runs
from cadenzra.verification.transposition import (
    Relation,
    UnknownRelationError,
    parse_relation,
)
from cadenzra.verification.voice import deficit_text

SOURCE: Final = "validate_motifs"

# docs/04 says a motif is "typically 1-4 bars". That was guidance; it is now a
# check, because motif length is what makes declared entries reproducible or
# not. Every entry must be written out note for note and is verified as strict
# interval equality, so a twenty-three-note subject asks a generator to
# transcribe a long line exactly, several times, in different voices — and the
# commission run showed it failing that and burning its whole budget on it. A
# short subject is also better music: material has to be recognizable when it
# returns, which is the entire reason it is in the piece.
MAX_MOTIF_NOTES: Final = 12


def validate_motifs(
    motifs: MotifLibrary,
    plan: StructurePlan,
    spec: PieceSpec,
    renderer: ScoreRenderer,
    workdir: Path,
    *,
    parallel_policy: str = "forbid",
) -> list[FeedbackItem]:
    """Check every motif. An empty list means the library is accepted."""
    feedback = []
    events_by_motif: dict[str, list[NoteEvent]] = {}

    for brief in plan.materials_needed:
        if brief.motif_id not in motifs:
            feedback.append(
                _item(
                    brief.motif_id,
                    message=(
                        f"the piece needs a {brief.role} called {brief.motif_id!r} "
                        "but none was written"
                    ),
                )
            )

    for motif_id, motif in sorted(motifs.motifs.items()):
        meter = _meter_for(motif_id, plan, spec)
        notes, events, compiler_output, bar_checks = _compiled_pitches(
            motif, meter, renderer, workdir / motif_id
        )
        if events:
            events_by_motif[motif_id] = events
        if notes is None:
            # The compiler said how much each bar is short or over; saying
            # only "its bars do not fill the meter" throws that away, and a
            # hook that was an eighth short came back an eighth short three
            # times running. Bar checks are warnings, so `first_error` finds
            # nothing and the paraphrase was all that was left.
            reason = first_error(compiler_output) or _bar_check_reason(bar_checks, meter)
            feedback.append(
                _item(
                    motif_id,
                    message=(
                        f"the {motif.role} {motif_id!r} is not usable in "
                        f"{meter.surface_string()}: "
                        + (reason or "its bars do not fill the meter")
                        + ". Write plain LilyPond: absolute pitch with Dutch note "
"names — a flat adds -es and a sharp adds -is on every letter "
                        "(ces des ees fes ges aes bes, cis dis eis fis gis "
                        "ais bis), never cb or eb or f#. An explicit "
                        "duration on every note, a bar check | at every barline, and "
                        f"every bar filling {meter.surface_string()} exactly"
                    ),
                    evidence=compiler_output,
                )
            )
            continue
        if not notes:
            feedback.append(
                _item(motif_id, message=f"the {motif.role} {motif_id!r} has no notes")
            )
            continue
        if len(notes) > MAX_MOTIF_NOTES:
            feedback.append(
                _item(
                    motif_id,
                    message=(
                        f"the {motif.role} {motif_id!r} is {len(notes)} notes long; "
                        f"keep it to {MAX_MOTIF_NOTES} or fewer, a phrase of one to "
                        "four bars. Every entry has to be written out exactly, and a "
                        "long line is neither reproducible nor recognizable when it "
                        "returns"
                    ),
                )
            )
            continue
        feedback += _check_range_under_relations(motif, notes, events, plan, spec)

    feedback += _check_entry_collisions(events_by_motif, plan, spec, parallel_policy)
    return feedback


def _check_entry_collisions(
    events: dict[str, list[NoteEvent]],
    plan: StructurePlan,
    spec: PieceSpec,
    policy: str,
) -> list[FeedbackItem]:
    """Overlapping prescribed entries, checked against each other now.

    Two subjects entered together as the plan declares can move in parallel
    octaves — a contradiction with no fixable side once the piece is built,
    because both lines are prescribed note-for-note. Each entry is placed at
    the register the prescription will choose — the same whole-octave
    arithmetic — because parallels are octave-sensitive: a live stretto's
    written fourths became sounding fifths when one voice was lifted to
    clear its floor, and the check had cleared the plan.
    """
    if policy != "forbid":
        return []
    feedback = []
    for section in plan.sections:
        placed: list[tuple[MaterialEntry, list[NoteEvent]]] = []
        for entry in section.material:
            notes = events.get(entry.motif_id)
            if not notes:
                continue
            try:
                relation = parse_relation(entry.relation)
            except UnknownRelationError:
                # The structure validator owns this failure.
                continue
            predicted = predicted_entry(notes, relation.kind, relation.semitones)
            if predicted is None:
                continue
            voice = spec.voices_by_id[entry.voice_id]
            displacement = octave_displacement(
                [note.midi_pitch for note in predicted],
                voice.range_low,
                voice.range_high,
            )
            if displacement is None:
                continue  # the octave-fit check owns this failure
            shift = offset_of(entry.bar, 1, section.meter)
            placed.append(
                (
                    entry,
                    [
                        note.model_copy(
                            update={
                                "onset": note.onset + shift,
                                "midi_pitch": note.midi_pitch + displacement,
                            }
                        )
                        for note in predicted
                    ],
                )
            )
        for (first, first_notes), (second, second_notes) in combinations(placed, 2):
            if first.voice_id == second.voice_id:
                continue
            for interval, onsets in parallel_runs(first_notes, second_notes):
                feedback.append(
                    _item(
                        first.motif_id,
                        section_id=section.section_id,
                        message=(
                            f"entered as declared in section {section.section_id}, "
                            f"{first.motif_id!r} ({first.voice_id}) and "
                            f"{second.motif_id!r} ({second.voice_id}) move in "
                            f"parallel {interval} from bar "
                            f"{bar_containing(onsets[0], section.meter)} — both "
                            "lines are prescribed note-for-note, so no voice can "
                            "fix this later; reshape one of the two"
                        ),
                    )
                )
    return feedback


def _meter_for(motif_id: str, plan: StructurePlan, spec: PieceSpec) -> MeterSpec:
    """The meter a motif is written in — shared with the prompt builder, so
    what the model is told and what it is checked against cannot drift."""
    return plan.meter_declaring(motif_id) or spec.meters_allowed[0]


def _compiled_pitches(
    motif: Motif, meter: MeterSpec, renderer: ScoreRenderer, workdir: Path
) -> tuple[list[int] | None, list[NoteEvent], str, list[BarCheckWarning]]:
    """The motif's MIDI pitches and the compiler's output.

    A motif is checked the same way a voice fragment is — scaffolded, compiled,
    analyzed — because it is the same kind of artifact under the same contract.
    The compiler output travels back with the verdict because it is the
    evidence a regeneration prompt needs (docs/06).
    """
    scaffolded = scaffold_fragment(motif.lily_music, meter)
    try:
        result = renderer.compile(scaffolded.source, workdir)
    except LilypondCompileError as error:
        return None, [], error.output, []
    if result.midi_path is None:
        return None, [], result.raw_output, []
    if result.bar_check_warnings:
        # A motif whose bars do not fill the meter it will be sung in cannot be
        # entered without either breaking its rhythm or breaking the bar. The
        # voice validator has always treated this as a failure; this one was
        # letting it through as a warning.
        return None, [], result.raw_output, result.bar_check_warnings

    pitches = []
    events: list[NoteEvent] = []
    for notes in extract_voice_notes(mido.MidiFile(result.midi_path)).values():
        pitches += [note.midi_pitch for note in notes]
        events += notes
    events.sort(key=lambda note: note.onset)
    return sorted(pitches), events, result.raw_output, []


def _bar_check_reason(
    warnings: list[BarCheckWarning], meter: MeterSpec
) -> str | None:
    """The compiler's own arithmetic on which bars fail and by how much."""
    if not warnings:
        return None
    parts = []
    for index, warning in enumerate(warnings, 1):
        deficit = deficit_text(warning.message, meter)
        parts.append(
            f"bar {index} is {deficit}" if deficit else f"bar {index} does not fill"
        )
    return "; ".join(parts)


def _check_range_under_relations(
    motif: Motif,
    pitches: list[int],
    events: list[NoteEvent],
    plan: StructurePlan,
    spec: PieceSpec,
) -> list[FeedbackItem]:
    """Every voice that carries this motif must be able to sing every entry.

    Fit is judged **allowing octave displacement**, because that is how the
    music works: a viola taking a subject "an octave down" plays it in the
    viola's own octave, and any entry may be placed an octave away without
    ceasing to be that subject. Judging the written pitch absolutely would
    demand a single motif that literally fits every voice under every relation
    at once — for a four-voice fugue spanning cello to violin that is often an
    interval of a second, i.e. impossible, and the validator would be rejecting
    correct music.

    What survives the relaxation is the check that actually matters: whether
    the subject's *span* fits inside the voice's range at all. A subject wider
    than the voice can sing is unsingable in every octave, and that is a real
    failure the fugue would otherwise carry to the end.
    """
    lowest, highest = min(pitches), max(pitches)
    feedback = []

    for section in plan.sections:
        for entry in section.material:
            if entry.motif_id != motif.motif_id:
                continue
            voice = spec.voices_by_id.get(entry.voice_id)
            if voice is None:
                continue
            try:
                relation = parse_relation(entry.relation)
            except UnknownRelationError:
                # The structure validator owns this failure; reporting it twice
                # would send the same problem to two nodes.
                continue

            span = highest - lowest
            voice_span_semitones = (
                voice.range_high.cents - voice.range_low.cents
            ) / 100
            if span <= voice_span_semitones:
                # Width fits — but entries are placed by whole octaves (every
                # downstream check is octave-blind), and a line can fit no
                # k*12 even when its span does: +0 dips under the floor, +12
                # tops the ceiling. That motif is unsingable in this voice
                # however it is entered.
                realized = _realized_pitches(events, relation)
                if (
                    realized is not None
                    and octave_displacement(
                        realized, voice.range_low, voice.range_high
                    )
                    is None
                ):
                    feedback.append(
                        _item(
                            motif.motif_id,
                            section_id=section.section_id,
                            voice_id=entry.voice_id,
                            message=(
                                f"the {motif.role} fits no whole-octave "
                                f"placement inside the {entry.voice_id} range "
                                f"{voice.range_low.to_scientific()} to "
                                f"{voice.range_high.to_scientific()} under "
                                f"{relation.describe()} — its low and high "
                                "notes straddle both limits; narrow or "
                                f"reposition the {motif.role}"
                            ),
                        )
                    )
                continue

            feedback.append(
                _item(
                    motif.motif_id,
                    section_id=section.section_id,
                    voice_id=entry.voice_id,
                    message=(
                        f"the {motif.role} spans {span} semitones, more than the "
                        f"{entry.voice_id} range of "
                        f"{voice.range_low.to_scientific()} to "
                        f"{voice.range_high.to_scientific()}, so the entry at bar "
                        f"{entry.bar} of section {section.section_id} "
                        f"({relation.describe()}) cannot be sung in any octave; "
                        f"narrow the {motif.role}"
                    ),
                )
            )
    return feedback


def _realized_pitches(
    events: list[NoteEvent], relation: Relation
) -> list[int] | None:
    """The entry's sounding pitches under the relation, or None.

    `predicted_entry` realizes tonal answers as the literal fifth-up answer;
    the adjust-license moves single notes by a step, which whole-octave fit
    is insensitive to.
    """
    if not events:
        return None
    predicted = predicted_entry(events, relation.kind, relation.semitones)
    if predicted is None:
        return None
    return [event.midi_pitch for event in predicted]


def _item(
    motif_id: str,
    *,
    message: str,
    section_id: str | None = None,
    voice_id: str | None = None,
    evidence: str | None = None,
) -> FeedbackItem:
    return FeedbackItem(
        source=SOURCE,
        level="motif",
        section_id=section_id,
        voice_id=voice_id,
        message=message,
        evidence=evidence or f"motif: {motif_id}",
    )
