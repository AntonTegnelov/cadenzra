"""Contrapuntal sections write their voices in entry order, each seeing the last.

The double-fugue's first pass produced ~44 distinct parallel passages because
four voices wrote against the same harmony grid blind to each other — the grid
constrains pitch class, not motion. Counterpoint is written against a fixed
line, so imitative textures generate sequentially with the finished lines in
context; homophony keeps the concurrent fan-out (docs/04:59 licenses exactly
this branch).
"""

from pathlib import Path

from cadenzra.app.compose import ComposeServices, generate_voices
from cadenzra.app.config import RetryBudgets
from cadenzra.model.motif import Motif, MotifLibrary
from cadenzra.model.primitives.meter import simple_meter
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.spec import PieceSpec, VoiceSpec
from cadenzra.model.state import PipelineState
from cadenzra.model.structure import (
    DynamicsPlan,
    MaterialEntry,
    SectionPlan,
    StructurePlan,
)
from cadenzra.model.style import StylePack
from tests.fakes.generator import ScriptedGenerator
from tests.fakes.renderer import RecordingRenderer

FOUR_FOUR = simple_meter(4, 4)

ALTO = VoiceSpec(
    voice_id="alto",
    kind="vocal",
    range_low=Pitch(step="G", octave=3),
    range_high=Pitch(step="C", octave=5),
    midi_program=52,
)
VIOLA = VoiceSpec(
    voice_id="viola",
    kind="instrument",
    range_low=Pitch(step="C", octave=3),
    range_high=Pitch(step="E", octave=5),
    midi_program=41,
)

ALTO_MUSIC = "a'4 b'4 c''4 a'4 |\n" * 3 + "a'1 |"
VIOLA_MUSIC = "c'4 d'4 e'4 c'4 |\n" * 3 + "c'1 |"

# The viola enters first even though the alto sorts first alphabetically —
# entry order is musical order, not name order.
ENTRIES = [
    MaterialEntry(motif_id="m", voice_id="viola", bar=1, relation="exact"),
    MaterialEntry(motif_id="m", voice_id="alto", bar=3, relation="P5 up"),
]


def _section(texture: str, *, entries: bool = True) -> SectionPlan:
    return SectionPlan(
        section_id="A",
        bars=4,
        meter=FOUR_FOUR,
        key="c major",
        tempo_bpm=90,
        texture=texture,
        dynamics=DynamicsPlan(start="mf"),
        active_voices=["alto", "viola"],
        material=ENTRIES if entries else [],
    )


def _state(section: SectionPlan) -> PipelineState:
    return PipelineState(
        spec=PieceSpec(
            title="T",
            style_prompt="s",
            voices=[ALTO, VIOLA],
            meters_allowed=[FOUR_FOUR],
            target_minutes=16 / 90,
        ),
        style=StylePack(),
        structure=StructurePlan(sections=[section]),
        motifs=MotifLibrary(
            motifs={"m": Motif(motif_id="m", role="subject", lily_music=VIOLA_MUSIC)}
        ),
    )


def _services(generator: ScriptedGenerator, tmp_path: Path) -> ComposeServices:
    return ComposeServices(
        generator=generator,
        renderer=RecordingRenderer(),
        workdir=tmp_path,
        budgets=RetryBudgets(),
        synthesizer=None,  # type: ignore[arg-type]
        output_dir=tmp_path,
    )


def test_an_imitative_section_writes_voices_in_entry_order_with_siblings(
    tmp_path: Path,
) -> None:
    generator = ScriptedGenerator(
        by_voice={("A", "alto"): ALTO_MUSIC, ("A", "viola"): VIOLA_MUSIC}
    )

    generate_voices(_state(_section("imitative")), _services(generator, tmp_path))

    order = [ctx.voice.voice_id for ctx in generator.contexts]
    assert order == ["viola", "alto"], "entry order, not alphabetical order"
    assert generator.contexts[0].siblings == {}, "the first entry writes alone"
    assert generator.contexts[1].siblings == {"viola": VIOLA_MUSIC}, (
        "the answer sees the finished subject it must fit against"
    )


def test_a_homophonic_section_keeps_the_independent_fan_out(tmp_path: Path) -> None:
    generator = ScriptedGenerator(
        by_voice={("A", "alto"): ALTO_MUSIC, ("A", "viola"): VIOLA_MUSIC}
    )

    generate_voices(
        _state(_section("homophonic", entries=False)),
        _services(generator, tmp_path),
    )

    assert all(ctx.siblings == {} for ctx in generator.contexts), (
        "independence given the skeleton stays the rule where it is cheap and safe"
    )


def test_fugal_and_canonic_textures_count_as_contrapuntal(tmp_path: Path) -> None:
    from cadenzra.app.compose import _is_contrapuntal

    assert _is_contrapuntal("imitative")
    assert _is_contrapuntal("fugal exposition")
    assert _is_contrapuntal("strict canon at the fifth")
    assert _is_contrapuntal("dense polyphonic web")
    assert _is_contrapuntal("contrapuntal")
    assert not _is_contrapuntal("homophonic")
    assert not _is_contrapuntal("melody and accompaniment")
