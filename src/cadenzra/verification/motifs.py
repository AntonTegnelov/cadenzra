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
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.spec import PieceSpec
from cadenzra.model.structure import StructurePlan
from cadenzra.notation.scaffold import scaffold_fragment
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
        notes = _compiled_pitches(motif, meter, renderer, workdir / motif_id)
        if notes is None:
            feedback.append(
                _item(
                    motif_id,
                    message=(
                        f"the {motif.role} {motif_id!r} does not compile; check that "
                        "every note has an explicit duration and every bar ends with |"
                    ),
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
) -> list[int] | None:
    """The motif's MIDI pitches, or None if it does not compile.

    A motif is checked the same way a voice fragment is — scaffolded, compiled,
    analyzed — because it is the same kind of artifact under the same contract.
    """
    scaffolded = scaffold_fragment(motif.lily_music, meter)
    try:
        result = renderer.compile(scaffolded.source, workdir)
    except LilypondCompileError:
        return None
    if result.midi_path is None:
        return None

    pitches = []
    for notes in extract_voice_notes(mido.MidiFile(result.midi_path)).values():
        pitches += [note.midi_pitch for note in notes]
    return sorted(pitches)


def _check_range_under_relations(
    motif: Motif, pitches: list[int], plan: StructurePlan, spec: PieceSpec
) -> list[FeedbackItem]:
    """Every voice that carries this motif must be able to sing every entry."""
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

            shift = relation.semitones
            low = Pitch.from_midi_number(lowest + shift)
            high = Pitch.from_midi_number(highest + shift)

            if low.cents < voice.range_low.cents:
                feedback.append(
                    _item(
                        motif.motif_id,
                        section_id=section.section_id,
                        voice_id=entry.voice_id,
                        message=(
                            f"the {entry.voice_id} entry at bar {entry.bar} of section "
                            f"{section.section_id} ({relation.describe()}) would reach "
                            f"{low.to_scientific()}, below the {entry.voice_id} floor of "
                            f"{voice.range_low.to_scientific()}; write the {motif.role} "
                            "higher or narrow its range"
                        ),
                    )
                )
            if high.cents > voice.range_high.cents:
                feedback.append(
                    _item(
                        motif.motif_id,
                        section_id=section.section_id,
                        voice_id=entry.voice_id,
                        message=(
                            f"the {entry.voice_id} entry at bar {entry.bar} of section "
                            f"{section.section_id} ({relation.describe()}) would reach "
                            f"{high.to_scientific()}, above the {entry.voice_id} ceiling "
                            f"of {voice.range_high.to_scientific()}; write the "
                            f"{motif.role} lower or narrow its range"
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
) -> FeedbackItem:
    return FeedbackItem(
        source=SOURCE,
        level="motif",
        section_id=section_id,
        voice_id=voice_id,
        message=message,
        evidence=f"motif: {motif_id}",
    )
