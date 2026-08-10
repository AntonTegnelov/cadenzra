"""Resume: a run picks up from its own written state instead of re-buying it.

The cost audit's largest single finding — 79.5% of all spend went to re-runs of
specs already attempted, every one restarting at derive_style. These tests pin
the contract: a layer whose state slice is present does not generate, a layer
whose slice is missing does, and the loader refuses anything it cannot
truthfully resume.
"""

from fractions import Fraction
from pathlib import Path

import pytest

from cadenzra.app.compose import ComposeServices, generate_voices, load_resume_state
from cadenzra.app.config import RetryBudgets
from cadenzra.app.pipeline import (
    LayerServices,
    derive_style,
    generate_harmony,
    generate_motifs,
    plan_lyrics,
    plan_structure,
)
from cadenzra.common.errors import CadenzraError
from cadenzra.model.harmony import HarmonicEvent, HarmonicSkeleton
from cadenzra.model.primitives.meter import simple_meter
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.spec import PieceSpec, VoiceSpec
from cadenzra.model.state import PipelineState, voice_key
from cadenzra.model.structure import DynamicsPlan, SectionPlan, StructurePlan
from cadenzra.model.style import StylePack
from cadenzra.model.voice import VoicePart
from tests.fakes.generator import ScriptedGenerator
from tests.fakes.renderer import RecordingRenderer

SEVEN_EIGHT = simple_meter(7, 8, [2, 2, 3])

ALTO = VoiceSpec(
    voice_id="alto",
    kind="vocal",
    range_low=Pitch(step="G", octave=3),
    range_high=Pitch(step="C", octave=5),
    midi_program=52,
)
SOPRANO = VoiceSpec(
    voice_id="soprano",
    kind="vocal",
    range_low=Pitch(step="C", octave=4),
    range_high=Pitch(step="A", octave=5),
    midi_program=52,
)

SECTION = SectionPlan(
    section_id="A",
    bars=1,
    meter=SEVEN_EIGHT,
    key="d minor",
    tempo_bpm=96,
    texture="homophonic",
    dynamics=DynamicsPlan(start="mf"),
    active_voices=["alto", "soprano"],
)

SPEC = PieceSpec(
    title="T",
    style_prompt="s",
    voices=[ALTO, SOPRANO],
    meters_allowed=[SEVEN_EIGHT],
    target_minutes=1.0,
)

GOOD = "a'8 a' b' b' c''4. |"

SKELETON = HarmonicSkeleton(
    section_id="A",
    events=[HarmonicEvent(offset=Fraction(0), duration=Fraction(7, 8), chord="Dm")],
)


class _Untouchable:
    """A generator that fails the test the moment any capability is invoked."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"generator.{name} was called for an already-present layer")


def _scaffolded() -> PipelineState:
    return PipelineState(
        spec=SPEC,
        style=StylePack(),
        structure=StructurePlan(sections=[SECTION]),
        harmony={"A": SKELETON},
    )


def _layer_services(tmp_path: Path) -> LayerServices:
    return LayerServices(
        generator=_Untouchable(),  # type: ignore[arg-type]
        renderer=RecordingRenderer(),
        workdir=tmp_path,
        budgets=RetryBudgets(),
    )


def test_completed_layers_do_not_generate_again(tmp_path: Path) -> None:
    state = _scaffolded()
    services = _layer_services(tmp_path)

    assert derive_style(state, services) == state
    assert plan_structure(state, services) == state
    assert generate_harmony(state, services) == state
    # No lyric plan present but the spec is instrumental-shaped either way;
    # motifs: the plan declares no material, and a present library also skips.
    assert generate_motifs(state, services) == state
    assert plan_lyrics(state, services) == state


def test_only_the_missing_voice_is_generated(tmp_path: Path) -> None:
    """Two of three slices present means one generation, not three."""
    existing = VoicePart(section_id="A", voice_id="alto", lily_music=GOOD)
    state = _scaffolded().model_copy(
        update={"voices": {voice_key("A", "alto"): existing}}
    )
    generator = ScriptedGenerator(by_voice={("A", "soprano"): GOOD})
    services = ComposeServices(
        generator=generator,
        renderer=RecordingRenderer(),
        workdir=tmp_path,
        budgets=RetryBudgets(),
        synthesizer=None,  # type: ignore[arg-type]
        output_dir=tmp_path,
    )

    result = generate_voices(state, services)

    assert generator.calls == 1
    assert [ctx.voice.voice_id for ctx in generator.contexts] == ["soprano"]
    assert result.voices[voice_key("A", "alto")] is existing, "kept, not rewritten"
    assert result.voices[voice_key("A", "soprano")].lily_music == GOOD


def test_the_loader_round_trips_and_clears_downstream_residue(tmp_path: Path) -> None:
    """Assembly, render and critique always re-run: their inputs may include
    freshly generated voices, so stale sections or scores would be lies."""
    state = _scaffolded().model_copy(
        update={
            "voices": {
                voice_key("A", "alto"): VoicePart(
                    section_id="A", voice_id="alto", lily_music=GOOD
                )
            },
            "feedback": [],
        }
    )
    (tmp_path / "state.json").write_text(state.model_dump_json(), encoding="utf-8")

    loaded = load_resume_state(tmp_path, SPEC)

    assert loaded.style == state.style
    assert loaded.harmony == state.harmony
    assert loaded.voices.keys() == state.voices.keys()
    assert loaded.sections == {}
    assert loaded.score is None
    assert loaded.artifacts is None
    assert loaded.feedback == []


def test_the_loader_refuses_a_mismatched_spec(tmp_path: Path) -> None:
    """Resuming another piece's state would silently compose the wrong music."""
    state = _scaffolded()
    (tmp_path / "state.json").write_text(state.model_dump_json(), encoding="utf-8")
    other = SPEC.model_copy(update={"title": "Another piece"})

    with pytest.raises(CadenzraError, match="spec"):
        load_resume_state(tmp_path, other)


def test_the_loader_refuses_when_nothing_was_written(tmp_path: Path) -> None:
    with pytest.raises(CadenzraError, match="state.json"):
        load_resume_state(tmp_path, SPEC)
