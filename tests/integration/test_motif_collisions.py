"""Overlapping prescribed entries are checked against each other at motif time.

The double-fugue's two subjects, entered together as the plan declares, move
in parallel octaves — a contradiction with no fixable side once the piece is
built, because both lines are prescribed note-for-note. Their realizations
are fully determined for exact and transposed entries, so the collision is
checkable the moment the motifs exist, for the price of two compiles.
"""

from pathlib import Path

import pytest

from cadenzra.model.motif import Motif, MotifLibrary
from cadenzra.model.primitives.meter import simple_meter
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.spec import PieceSpec, VoiceSpec
from cadenzra.model.structure import (
    DynamicsPlan,
    MaterialEntry,
    SectionPlan,
    StructurePlan,
)
from cadenzra.rendering.lilypond import LilypondAdapter
from cadenzra.verification.motifs import validate_motifs

pytestmark = pytest.mark.integration

FOUR_FOUR = simple_meter(4, 4)

SOPRANO = VoiceSpec(
    voice_id="soprano",
    kind="vocal",
    range_low=Pitch(step="C", octave=4),
    range_high=Pitch(step="G", octave=5),
    midi_program=52,
)
ALTO = VoiceSpec(
    voice_id="alto",
    kind="vocal",
    range_low=Pitch(step="G", octave=3),
    range_high=Pitch(step="C", octave=5),
    midi_program=52,
)

SPEC = PieceSpec(
    title="T",
    style_prompt="s",
    voices=[SOPRANO, ALTO],
    meters_allowed=[FOUR_FOUR],
    target_minutes=4 / 90,
)


def _plan(*entries: MaterialEntry) -> StructurePlan:
    return StructurePlan(
        sections=[
            SectionPlan(
                section_id="A",
                bars=1,
                meter=FOUR_FOUR,
                key="c major",
                tempo_bpm=90,
                texture="imitative",
                dynamics=DynamicsPlan(start="mf"),
                active_voices=["soprano", "alto"],
                material=list(entries),
            )
        ]
    )


def _library(upper: str, lower: str) -> MotifLibrary:
    return MotifLibrary(
        motifs={
            "upper": Motif(motif_id="upper", role="subject", lily_music=upper),
            "lower": Motif(motif_id="lower", role="subject", lily_music=lower),
        }
    )


BOTH_AT_ONE = (
    MaterialEntry(motif_id="upper", voice_id="soprano", bar=1, relation="exact"),
    MaterialEntry(motif_id="lower", voice_id="alto", bar=1, relation="exact"),
)


def test_two_subjects_entered_in_parallel_octaves_are_rejected_together(
    tmp_path: Path,
) -> None:
    feedback = validate_motifs(
        _library("c''4 d''4 e''4 f''4 |", "c'4 d'4 e'4 f'4 |"),
        _plan(*BOTH_AT_ONE),
        SPEC,
        LilypondAdapter(),
        tmp_path,
        parallel_policy="forbid",
    )

    collision = [item for item in feedback if "parallel" in item.message]
    assert collision, "the colliding pair is flagged before anything is built"
    assert any(
        "upper" in item.message and "lower" in item.message for item in collision
    ), "both motifs are named, so the regeneration knows which pair to reshape"


def test_compatible_subjects_pass(tmp_path: Path) -> None:
    feedback = validate_motifs(
        _library("c''4 d''4 e''4 d''4 |", "c'4 b4 c'4 g4 |"),
        _plan(*BOTH_AT_ONE),
        SPEC,
        LilypondAdapter(),
        tmp_path,
        parallel_policy="forbid",
    )

    assert [item for item in feedback if "parallel" in item.message] == []


def test_a_permissive_policy_skips_the_collision_check(tmp_path: Path) -> None:
    feedback = validate_motifs(
        _library("c''4 d''4 e''4 f''4 |", "c'4 d'4 e'4 f'4 |"),
        _plan(*BOTH_AT_ONE),
        SPEC,
        LilypondAdapter(),
        tmp_path,
        parallel_policy="allow",
    )

    assert [item for item in feedback if "parallel" in item.message] == []
