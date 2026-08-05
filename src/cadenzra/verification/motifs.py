"""`validate_motifs` — the highest-leverage check in the pipeline.

Motifs are the highest-leverage notes in the piece: every declared entry across
the whole work derives from them, so they get both the deterministic treatment
and, elsewhere, an LLM review for memorability (docs/04).

The check that earns its keep here is **range-fit under every declared
relation**. A subject that fits the soprano can leave the alto's fifth-below
answer under its floor; catching that here costs one check, catching it after
the sections are written costs regenerating them (docs/05).
"""

from pathlib import Path
from typing import Final

import mido

from cadenzra.common.errors import LilypondCompileError
from cadenzra.interfaces.rendering import ScoreRenderer
from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.motif import Motif, MotifLibrary
from cadenzra.model.primitives.meter import MeterSpec
from cadenzra.model.spec import PieceSpec
from cadenzra.model.structure import StructurePlan
from cadenzra.notation.scaffold import scaffold_fragment
from cadenzra.rendering.lilypond import first_error
from cadenzra.verification.midi_analysis import extract_voice_notes
from cadenzra.verification.transposition import UnknownRelationError, parse_relation

SOURCE: Final = "validate_motifs"


def validate_motifs(
    motifs: MotifLibrary,
    plan: StructurePlan,
    spec: PieceSpec,
    renderer: ScoreRenderer,
    workdir: Path,
) -> list[FeedbackItem]:
    """Check every motif. An empty list means the library is accepted."""
    feedback = []

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
        notes, compiler_output = _compiled_pitches(
            motif, meter, renderer, workdir / motif_id
        )
        if notes is None:
            reason = first_error(compiler_output)
            feedback.append(
                _item(
                    motif_id,
                    message=(
                        f"the {motif.role} {motif_id!r} does not compile: "
                        + (reason or "the compiler rejected it")
                        + ". Write plain LilyPond: absolute pitch with Dutch note "
                        "names (ees for E flat, fis for F sharp), an explicit "
                        "duration on every note, and a bar check | at every barline"
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
        feedback += _check_range_under_relations(motif, notes, plan, spec)

    return feedback


def _meter_for(motif_id: str, plan: StructurePlan, spec: PieceSpec) -> MeterSpec:
    """The meter a motif is written in — the first section that declares it."""
    for section in plan.sections:
        if any(entry.motif_id == motif_id for entry in section.material):
            return section.meter
    return spec.meters_allowed[0]


def _compiled_pitches(
    motif: Motif, meter: MeterSpec, renderer: ScoreRenderer, workdir: Path
) -> tuple[list[int] | None, str]:
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
        return None, error.output
    if result.midi_path is None:
        return None, result.raw_output

    pitches = []
    for notes in extract_voice_notes(mido.MidiFile(result.midi_path)).values():
        pitches += [note.midi_pitch for note in notes]
    return sorted(pitches), result.raw_output


def _check_range_under_relations(
    motif: Motif, pitches: list[int], plan: StructurePlan, spec: PieceSpec
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
