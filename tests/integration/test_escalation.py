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


def _solo_grid_state(chord: str) -> PipelineState:
    """One prescribed line holding ees'' over the given chord."""
    held = "ees''2. ees''4 |"
    solo = SECTION.model_copy(
        update={
            "active_voices": ["soprano"],
            "material": [
                MaterialEntry(
                    motif_id="upper_subject",
                    voice_id="soprano",
                    bar=1,
                    relation="exact",
                )
            ],
        }
    )
    spec = PieceSpec(
        title="Grid contradiction",
        style_prompt="s",
        voices=[UPPER],
        meters_allowed=[FOUR_FOUR],
        target_minutes=4 / 90,
    )
    return PipelineState(
        spec=spec,
        style=StylePack(),
        structure=StructurePlan(sections=[solo]),
        motifs=MotifLibrary(
            motifs={
                "upper_subject": Motif(
                    motif_id="upper_subject", role="subject", lily_music=held
                )
            }
        ),
        harmony={
            "A": HarmonicSkeleton(
                section_id="A",
                events=[
                    HarmonicEvent(offset=Fraction(0), duration=Fraction(1), chord=chord)
                ],
            )
        },
        voices={
            voice_key("A", "soprano"): VoicePart(
                section_id="A", voice_id="soprano", lily_music=held
            )
        },
    )


def test_a_grid_contradiction_loops_back_to_the_harmony_layer(tmp_path: Path) -> None:
    """The plan-time grid check cannot predict a tonal answer, so a
    contradiction can reach assembly: the subject holds ees'' where the grid
    says G7, and no voice is free to move. The fix belongs to the layer that
    owns the mistake — the grid regenerates once, with the violation quoted,
    before the run is allowed to go loud (CLAUDE.md: the fix loops back)."""
    from tests.fakes.generator import ScriptedGenerator

    fitting = HarmonicSkeleton(
        section_id="A",
        events=[HarmonicEvent(offset=Fraction(0), duration=Fraction(1), chord="Cm")],
    )
    generator = ScriptedGenerator(skeletons=[fitting])
    services = ComposeServices(
        generator=generator,
        renderer=LilypondAdapter(),
        workdir=tmp_path / "work",
        budgets=RetryBudgets(),
        synthesizer=None,  # type: ignore[arg-type]
        output_dir=tmp_path,
    )

    result = assemble_and_verify(_solo_grid_state("G7"), services)

    assert len(generator.harmony_contexts) == 1, "one regrid, not a repair sweep"
    (ctx,) = generator.harmony_contexts
    assert any("cannot change" in item.message for item in ctx.feedback), (
        "the grid is told the held note is pinned"
    )
    assert result.harmony["A"] == fitting


def test_a_regrid_that_cannot_satisfy_the_entry_still_goes_loud(
    tmp_path: Path,
) -> None:
    """The regenerated grid is validated against the entries before it is
    accepted; a model that keeps declaring G7 under a pinned ees'' exhausts
    the harmony budget loudly instead of bouncing the contradiction back."""
    from tests.fakes.generator import ScriptedGenerator

    still_wrong = HarmonicSkeleton(
        section_id="A",
        events=[HarmonicEvent(offset=Fraction(0), duration=Fraction(1), chord="G7")],
    )
    generator = ScriptedGenerator(skeletons=[still_wrong])
    services = ComposeServices(
        generator=generator,
        renderer=LilypondAdapter(),
        workdir=tmp_path / "work",
        budgets=RetryBudgets(),
        synthesizer=None,  # type: ignore[arg-type]
        output_dir=tmp_path,
    )

    with pytest.raises(BudgetExhaustedError, match="harmony for section A"):
        assemble_and_verify(_solo_grid_state("G7"), services)


def test_a_stalled_repair_loop_stops_at_the_plateau(tmp_path: Path) -> None:
    """A single immortal fault sits below the guard's noise floor — at the
    last few faults sweeps are cheap and Binomial noise dominates any
    trend (the simulation measured the trend guard killing 13% of
    converging loops there), so the section budget is the honest bound:
    the loop spends it and goes loud with the trajectory in hand."""
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
    # the loop cannot converge. Targets iterate in pair order (alto first),
    # and the script covers two full sweeps so each voice always gets its
    # own line back.
    generator = ScriptedGenerator(
        by_voice={("A", "soprano"): UPPER_MUSIC, ("A", "alto"): LOWER_MUSIC},
        patches=[{1: LOWER_MUSIC}, {1: UPPER_MUSIC}] * 12,
    )
    services = ComposeServices(
        generator=generator,
        renderer=LilypondAdapter(),
        workdir=tmp_path / "work",
        budgets=RetryBudgets(),
        synthesizer=None,  # type: ignore[arg-type]
        output_dir=tmp_path,
    )

    with pytest.raises(BudgetExhaustedError, match="still fails") as caught:
        assemble_and_verify(state, services)

    assert caught.value.attempts == RetryBudgets().section
    repairs = generator.calls + len(generator.patch_contexts)
    assert repairs <= 2 * RetryBudgets().section, "cheap tail sweeps, bounded"
