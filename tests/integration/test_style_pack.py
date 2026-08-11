"""The style pack is validated the way its docstring always claimed.

Cells and fragments are exemplars: every voice call copies and varies them,
so a cell that does not fill its bar, or a fragment carrying a forbidden
command, teaches the same mistake to the whole piece (the orchestra probe's
pack shipped `\\clef` fragments and no check existed to say so). Real
LilyPond, because the compiler is the only honest judge of "fills the bar" —
and its words are what the regeneration must read.
"""

from pathlib import Path

import pytest

from cadenzra.app.config import RetryBudgets
from cadenzra.app.pipeline import LayerServices, derive_style
from cadenzra.model.primitives.meter import simple_meter
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.spec import PieceSpec, VoiceSpec
from cadenzra.model.state import PipelineState
from cadenzra.model.style import RhythmicCell, StyleFragment, StylePack
from cadenzra.rendering.lilypond import LilypondAdapter
from cadenzra.verification.style import validate_style_pack
from tests.fakes.generator import ScriptedGenerator

pytestmark = pytest.mark.integration

SEVEN_EIGHT = simple_meter(7, 8, [2, 2, 3])

BAD_PACK = StylePack(
    # 6/8 of rhythm declared as a 7/8 cell: the compiler's bar check is the
    # judge, and its words are the feedback.
    rhythmic_cells=[
        RhythmicCell(meter=SEVEN_EIGHT, lily="c8 c c c c4", description="short")
    ],
    few_shot_fragments=[
        StyleFragment(meter=SEVEN_EIGHT, lily="\\clef treble a'8 a' b' b' c''4. |")
    ],
)
GOOD_PACK = StylePack(
    rhythmic_cells=[
        RhythmicCell(meter=SEVEN_EIGHT, lily="c8 c c c c4.", description="driving")
    ],
    few_shot_fragments=[
        StyleFragment(meter=SEVEN_EIGHT, lily="a'8 a' b' b' c''4. |")
    ],
)


def _spec() -> PieceSpec:
    alto = VoiceSpec(
        voice_id="alto",
        kind="vocal",
        range_low=Pitch(step="G", octave=3),
        range_high=Pitch(step="C", octave=5),
        midi_program=52,
    )
    return PieceSpec(
        title="T",
        style_prompt="s",
        voices=[alto],
        meters_allowed=[SEVEN_EIGHT],
        target_minutes=1.0,
    )


def test_a_bad_pack_is_rejected_with_both_faults_named(tmp_path: Path) -> None:
    feedback = validate_style_pack(BAD_PACK, _spec(), LilypondAdapter(), tmp_path)

    messages = " || ".join(item.message for item in feedback)
    assert "\\clef" in messages
    assert "c8 c c c c4" in messages, "the failing cell is quoted"
    assert "7/8" in messages


def test_a_good_pack_passes(tmp_path: Path) -> None:
    assert validate_style_pack(GOOD_PACK, _spec(), LilypondAdapter(), tmp_path) == []


def test_the_style_loop_feeds_rejection_back_and_converges(tmp_path: Path) -> None:
    """The feedback-reaches-the-regeneration contract, style edition: the
    second attempt must be shown why the first was rejected."""
    alto = VoiceSpec(
        voice_id="alto",
        kind="vocal",
        range_low=Pitch(step="G", octave=3),
        range_high=Pitch(step="C", octave=5),
        midi_program=52,
    )
    spec = PieceSpec(
        title="T",
        style_prompt="s",
        voices=[alto],
        meters_allowed=[SEVEN_EIGHT],
        target_minutes=1.0,
    )
    generator = ScriptedGenerator(styles=[BAD_PACK, GOOD_PACK])
    services = LayerServices(
        generator=generator,
        renderer=LilypondAdapter(),
        workdir=tmp_path,
        budgets=RetryBudgets(),
    )

    state = derive_style(PipelineState(spec=spec), services)

    assert state.style == GOOD_PACK
    assert generator.style_calls == 2
    assert generator.style_feedback[0] == []
    # Salvage drops the broken exemplars silently (they simply are not
    # exemplars); the actionable rejection is the hole they leave.
    assert any(
        "no rhythmic cells for 7/8" in item.message
        for item in generator.style_feedback[1]
    ), "the second attempt sees the coverage gap the drops exposed"


def test_a_pack_with_one_broken_cell_is_salvaged_not_retried(
    tmp_path: Path,
) -> None:
    """One bad dotted cell used to re-roll the whole pack (a live loop died
    at six attempts of near-misses). With a good cell beside it, salvage
    keeps the accepted material and the pack lands on the first attempt."""
    alto = VoiceSpec(
        voice_id="alto",
        kind="vocal",
        range_low=Pitch(step="G", octave=3),
        range_high=Pitch(step="C", octave=5),
        midi_program=52,
    )
    spec = PieceSpec(
        title="T",
        style_prompt="s",
        voices=[alto],
        meters_allowed=[SEVEN_EIGHT],
        target_minutes=1.0,
    )
    mixed = StylePack(
        rhythmic_cells=[
            RhythmicCell(meter=SEVEN_EIGHT, lily="c4. c4 c4 c4", description="bad"),
            RhythmicCell(meter=SEVEN_EIGHT, lily="c8 c c c c4.", description="good"),
        ],
        few_shot_fragments=[
            StyleFragment(meter=SEVEN_EIGHT, lily="a'8 a' b' b' c''4. |")
        ],
    )
    generator = ScriptedGenerator(styles=[mixed])
    services = LayerServices(
        generator=generator,
        renderer=LilypondAdapter(),
        workdir=tmp_path,
        budgets=RetryBudgets(),
    )

    state = derive_style(PipelineState(spec=spec), services)

    assert generator.style_calls == 1, "salvage, not a retry"
    assert state.style is not None
    assert [c.description for c in state.style.rhythmic_cells] == ["good"]
