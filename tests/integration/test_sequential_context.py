"""A sequential voice is judged against the finished lines at the voice layer.

Round 7's double-fugue, live: the second violin's free counterpoint copied the
first violin's shown line for whole stretches, the duplication survived every
per-voice check, and the section sweep inherited 177 cross-voice violations it
could only patch a passage at a time — plateauing at 89. The cross-voice
checks are decidable the moment the candidate exists, because its siblings are
already fixed; this drives the real pipeline (ScriptedGenerator, real
LilyPond) and asserts the duplication is caught and repaired inside the voice
loop, before the sweep ever sees it.
"""

from pathlib import Path

import pytest

from cadenzra.app.compose import ComposeServices, generate_voices
from cadenzra.app.config import RetryBudgets
from cadenzra.model.primitives.meter import simple_meter
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.spec import PieceSpec, VoiceSpec
from cadenzra.model.state import PipelineState, voice_key
from cadenzra.model.structure import DynamicsPlan, SectionPlan, StructurePlan
from cadenzra.model.style import StylePack
from cadenzra.rendering.lilypond import LilypondAdapter
from tests.fakes.generator import ScriptedGenerator

pytestmark = pytest.mark.integration

FOUR_FOUR = simple_meter(4, 4)

VIOLA = VoiceSpec(
    voice_id="viola",
    kind="instrument",
    range_low=Pitch(step="C", octave=3),
    range_high=Pitch(step="E", octave=6),
    midi_program=41,
)
ALTO = VoiceSpec(
    voice_id="alto",
    kind="vocal",
    range_low=Pitch(step="G", octave=3),
    range_high=Pitch(step="C", octave=6),
    midi_program=52,
)

VIOLA_LINE = "c'4 d'4 e'4 f'4 |\ng'4 f'4 e'4 c'4 |"
# The viola's line an octave up — parallel octaves on every beat.
ALTO_DOUBLING = "c''4 d''4 e''4 f''4 |\ng''4 f''4 e''4 c''4 |"
ALTO_FIX_1 = "e''4 d''4 c''4 a'4 |"
ALTO_FIX_2 = "b'4 c''4 g''4 e''4 |"


def _state() -> PipelineState:
    section = SectionPlan(
        section_id="A",
        bars=2,
        meter=FOUR_FOUR,
        key="c major",
        tempo_bpm=90,
        texture="imitative",
        dynamics=DynamicsPlan(start="mf"),
        active_voices=["viola", "alto"],
    )
    return PipelineState(
        spec=PieceSpec(
            title="T",
            style_prompt="s",
            voices=[VIOLA, ALTO],
            meters_allowed=[FOUR_FOUR],
            target_minutes=8 / 90,
        ),
        style=StylePack(parallel_fifths_policy="forbid"),
        structure=StructurePlan(sections=[section]),
    )


def test_a_doubled_line_is_caught_and_repaired_inside_the_voice_loop(
    tmp_path: Path,
) -> None:
    generator = ScriptedGenerator(
        [VIOLA_LINE, ALTO_DOUBLING],
        patches=[{1: ALTO_FIX_1, 2: ALTO_FIX_2}],
    )
    services = ComposeServices(
        generator=generator,
        renderer=LilypondAdapter(),
        workdir=tmp_path,
        budgets=RetryBudgets(),
        synthesizer=None,  # type: ignore[arg-type]
        output_dir=tmp_path,
    )

    state = generate_voices(_state(), services)

    assert generator.calls == 2, "one write per voice; the repair was a patch"
    (patch,) = generator.patch_contexts
    assert patch.voice.voice_id == "alto", "the finished viola never moves"
    parallels = [item for item in patch.feedback if item.kind == "parallels"]
    assert parallels, "the doubling was named before the patch was asked for"
    assert all(item.voice_id == "alto" for item in parallels)
    assert "octaves" in parallels[0].message
    alto = state.voices[voice_key("A", "alto")]
    assert ALTO_FIX_1.strip(" |") in alto.lily_music
    assert ALTO_FIX_2.strip(" |") in alto.lily_music
