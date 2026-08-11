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


def test_a_motif_with_no_whole_octave_fit_is_rejected(tmp_path: Path) -> None:
    """The span-only rule admits a motif that fits at *no* whole-octave
    placement: D3–E5 spans 26 against a G3–C6 voice's 29, yet +0 dips below
    the floor and +12 tops the ceiling. Entries are placed by whole octaves
    (every check is octave-blind), so this motif is unsingable in that voice
    and must be rejected before anything is built."""
    wide = VoiceSpec(
        voice_id="wide",
        kind="vocal",
        range_low=Pitch(step="G", octave=3),
        range_high=Pitch(step="C", octave=6),
        midi_program=52,
    )
    spec = SPEC.model_copy(update={"voices": [wide]})
    plan = _plan(
        MaterialEntry(motif_id="upper", voice_id="wide", bar=1, relation="exact")
    ).model_copy(deep=True)
    plan = StructurePlan(
        sections=[
            plan.sections[0].model_copy(update={"active_voices": ["wide"]})
        ]
    )
    library = MotifLibrary(
        motifs={
            "upper": Motif(
                motif_id="upper", role="subject", lily_music="d4 e''2 d4 |"
            )
        }
    )

    feedback = validate_motifs(
        library, plan, spec, LilypondAdapter(), tmp_path, parallel_policy="forbid"
    )

    assert any("whole-octave" in item.message for item in feedback)
    assert any("wide" in item.message for item in feedback)


def test_entries_collide_at_the_register_the_prescription_chooses(
    tmp_path: Path,
) -> None:
    """A live stretto slipped through: at written pitch the two subjects move
    in fourths, but the prescription lifts the violin an octave to clear its
    G3 floor, and fourths inverted become fifths. The collision check must
    place each entry where the prescription will — the same whole-octave
    arithmetic — or it clears plans the assembly then rejects with no voice
    free to fix."""
    violin1 = VoiceSpec(
        voice_id="violin1",
        kind="instrument",
        range_low=Pitch(step="G", octave=3),
        range_high=Pitch(step="E", octave=6),
        midi_program=41,
    )
    viola = VoiceSpec(
        voice_id="viola",
        kind="instrument",
        range_low=Pitch(step="C", octave=3),
        range_high=Pitch(step="E", octave=5),
        midi_program=42,
    )
    spec = SPEC.model_copy(update={"voices": [violin1, viola]})
    plan = StructurePlan(
        sections=[
            SectionPlan(
                section_id="A",
                bars=4,
                meter=FOUR_FOUR,
                key="c minor",
                tempo_bpm=90,
                texture="imitative",
                dynamics=DynamicsPlan(start="mf"),
                active_voices=["violin1", "viola"],
                material=[
                    MaterialEntry(
                        motif_id="s1", voice_id="violin1", bar=1, relation="exact"
                    ),
                    MaterialEntry(
                        motif_id="s2", voice_id="viola", bar=1, relation="exact"
                    ),
                ],
            )
        ]
    )
    # s1 written D3-G3 sits below the violin's floor, so its prescription is
    # lifted an octave; the viola's line needs no lift. At written pitch the
    # pair moves in fourths — only the lifted register makes them fifths.
    library = MotifLibrary(
        motifs={
            "s1": Motif(
                motif_id="s1", role="subject", lily_music="d4 e4 f4 g4 |"
            ),
            "s2": Motif(
                motif_id="s2", role="subject", lily_music="g4 a4 b4 c'4 |"
            ),
        }
    )

    feedback = validate_motifs(
        library, plan, spec, LilypondAdapter(), tmp_path, parallel_policy="forbid"
    )

    collision = [item for item in feedback if "parallel" in item.message]
    assert collision, "the stretto's fifths are caught before anything is built"
    assert any(
        "violin1" in item.message and "viola" in item.message for item in collision
    )


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
