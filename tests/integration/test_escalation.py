"""A plan-level contradiction fails immediately, not after the budget.

The double-fugue spent three full repair sweeps (40 minutes, 8.3% of the
audit's spend) on violations whose every side was prescribed material. This
drives the real pipeline — real LilyPond, real MIDI analysis — into that shape
and asserts the run goes loud before any voice is asked to fix the unfixable.
"""

from fractions import Fraction
from pathlib import Path

import pytest

from cadenzra.app.compose import ComposeServices, assemble_and_verify
from cadenzra.app.config import RetryBudgets
from cadenzra.common.errors import BudgetExhaustedError
from cadenzra.model.harmony import HarmonicEvent, HarmonicSkeleton
from cadenzra.model.motif import Motif, MotifLibrary
from cadenzra.model.primitives.meter import simple_meter
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.spec import PieceSpec, VoiceSpec
from cadenzra.model.state import PipelineState, voice_key
from cadenzra.model.structure import (
    DynamicsPlan,
    MaterialEntry,
    SectionPlan,
    StructurePlan,
)
from cadenzra.model.style import StylePack
from cadenzra.model.voice import VoicePart
from cadenzra.rendering.lilypond import LilypondAdapter

pytestmark = pytest.mark.integration

FOUR_FOUR = simple_meter(4, 4)

UPPER = VoiceSpec(
    voice_id="soprano",
    kind="vocal",
    range_low=Pitch(step="C", octave=4),
    range_high=Pitch(step="G", octave=5),
    midi_program=52,
)
LOWER = VoiceSpec(
    voice_id="alto",
    kind="vocal",
    range_low=Pitch(step="G", octave=3),
    range_high=Pitch(step="C", octave=5),
    midi_program=52,
)

# Parallel octaves throughout, and both lines are declared subjects — the
# checker must find nobody free to move.
UPPER_MUSIC = "c''4 d''4 e''4 f''4 |"
LOWER_MUSIC = "c'4 d'4 e'4 f'4 |"

SECTION = SectionPlan(
    section_id="A",
    bars=1,
    meter=FOUR_FOUR,
    key="c major",
    tempo_bpm=90,
    texture="imitative",
    dynamics=DynamicsPlan(start="mf"),
    active_voices=["soprano", "alto"],
    material=[
        MaterialEntry(motif_id="upper_subject", voice_id="soprano", bar=1, relation="exact"),
        MaterialEntry(motif_id="lower_subject", voice_id="alto", bar=1, relation="exact"),
    ],
)


class _Untouchable:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(
            f"generator.{name} was called to repair an unfixable violation"
        )


def test_two_prescribed_lines_in_parallel_fail_loudly_without_repair(
    tmp_path: Path,
) -> None:
    spec = PieceSpec(
        title="Contradiction",
        style_prompt="s",
        voices=[UPPER, LOWER],
        meters_allowed=[FOUR_FOUR],
        target_minutes=4 / 90,
    )
    state = PipelineState(
        spec=spec,
        style=StylePack(parallel_fifths_policy="forbid"),
        structure=StructurePlan(sections=[SECTION]),
        motifs=MotifLibrary(
            motifs={
                "upper_subject": Motif(
                    motif_id="upper_subject", role="subject", lily_music=UPPER_MUSIC
                ),
                "lower_subject": Motif(
                    motif_id="lower_subject", role="subject", lily_music=LOWER_MUSIC
                ),
            }
        ),
        harmony={
            "A": HarmonicSkeleton(
                section_id="A",
                events=[
                    HarmonicEvent(offset=Fraction(0), duration=Fraction(1), chord="C")
                ],
            )
        },
        voices={
            voice_key("A", "soprano"): VoicePart(
                section_id="A", voice_id="soprano", lily_music=UPPER_MUSIC
            ),
            voice_key("A", "alto"): VoicePart(
                section_id="A", voice_id="alto", lily_music=LOWER_MUSIC
            ),
        },
    )
    services = ComposeServices(
        generator=_Untouchable(),  # type: ignore[arg-type]
        renderer=LilypondAdapter(),
        workdir=tmp_path / "work",
        budgets=RetryBudgets(),
        synthesizer=None,  # type: ignore[arg-type]
        output_dir=tmp_path,
    )

    with pytest.raises(BudgetExhaustedError, match="free to fix"):
        assemble_and_verify(state, services)


def test_a_stalled_repair_loop_stops_at_the_plateau(tmp_path: Path) -> None:
    """263 → 63 → 66: the double-fugue's third sweep spent thirteen minutes
    proving what the second already had. When the distinct-violation count
    stops falling, the loop goes loud with the trajectory in hand."""
    from tests.fakes.generator import ScriptedGenerator

    free_section = SECTION.model_copy(update={"material": []})
    spec = PieceSpec(
        title="Plateau",
        style_prompt="s",
        voices=[UPPER, LOWER],
        meters_allowed=[FOUR_FOUR],
        target_minutes=4 / 90,
    )
    state = PipelineState(
        spec=spec,
        style=StylePack(parallel_fifths_policy="forbid"),
        structure=StructurePlan(sections=[free_section]),
        harmony={
            "A": HarmonicSkeleton(
                section_id="A",
                events=[
                    HarmonicEvent(offset=Fraction(0), duration=Fraction(1), chord="C")
                ],
            )
        },
        voices={
            voice_key("A", "soprano"): VoicePart(
                section_id="A", voice_id="soprano", lily_music=UPPER_MUSIC
            ),
            voice_key("A", "alto"): VoicePart(
                section_id="A", voice_id="alto", lily_music=LOWER_MUSIC
            ),
        },
    )
    # Every "repair" — patch or rewrite — returns the same parallel lines:
    # the loop cannot converge. Targets iterate in pair order (alto first).
    generator = ScriptedGenerator(
        by_voice={("A", "soprano"): UPPER_MUSIC, ("A", "alto"): LOWER_MUSIC},
        patches=[{1: LOWER_MUSIC}, {1: UPPER_MUSIC}],
    )
    services = ComposeServices(
        generator=generator,
        renderer=LilypondAdapter(),
        workdir=tmp_path / "work",
        budgets=RetryBudgets(),
        synthesizer=None,  # type: ignore[arg-type]
        output_dir=tmp_path,
    )

    with pytest.raises(BudgetExhaustedError, match="stopped converging") as caught:
        assemble_and_verify(state, services)

    assert "1 -> 1" in str(caught.value), "the trajectory is in the message"
    repairs = generator.calls + len(generator.patch_contexts)
    assert repairs <= 2, "one repair sweep, then the plateau went loud"
