"""Loop mechanics, entirely against fakes.

These assert the machinery the whole pipeline depends on: that feedback routes
back to the node that can fix it, that budgets decrement per loop key, that
exhaustion fails loudly with its evidence, and that superseded feedback is
cleared when its target regenerates (docs/09).
"""

from pathlib import Path

import pytest

from cadenzra.app.config import RetryBudgets
from cadenzra.common.errors import BudgetExhaustedError
from cadenzra.graph.build import build_voice_graph
from cadenzra.graph.nodes import Services
from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.primitives.meter import simple_meter
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.spec import PieceSpec, VoiceSpec
from cadenzra.model.state import PipelineState, attempt_key, voice_key
from cadenzra.model.structure import DynamicsPlan, SectionPlan, StructurePlan
from cadenzra.model.style import StylePack
from tests.fakes.generator import ScriptedGenerator
from tests.fakes.renderer import RecordingRenderer, clean, failing_bar_check

SEVEN_EIGHT = simple_meter(7, 8, [2, 2, 3])

ALTO = VoiceSpec(
    voice_id="alto",
    kind="vocal",
    range_low=Pitch(step="G", octave=3),
    range_high=Pitch(step="C", octave=5),
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
    active_voices=["alto"],
)

GOOD = "a'8 a' b' b' c''4. |"
BAD = "a'8 a' b' b' c''4 |"


def _state(**overrides: object) -> PipelineState:
    base = PipelineState(
        spec=PieceSpec(
            title="T",
            style_prompt="s",
            voices=[ALTO],
            meters_allowed=[SEVEN_EIGHT],
            target_minutes=1.0,
        ),
        style=StylePack(),
        structure=StructurePlan(sections=[SECTION]),
    )
    return base.model_copy(update=overrides)


def _services(
    generator: ScriptedGenerator,
    renderer: RecordingRenderer,
    tmp_path: Path,
    *,
    voice_budget: int = 3,
) -> Services:
    return Services(
        generator=generator,
        renderer=renderer,
        workdir=tmp_path,
        budgets=RetryBudgets(voice=voice_budget),
    )


def test_a_valid_fragment_passes_on_the_first_attempt(tmp_path: Path) -> None:
    generator = ScriptedGenerator([GOOD])
    graph = build_voice_graph(
        _services(generator, RecordingRenderer([clean()]), tmp_path), "A", "alto"
    )

    result = graph.invoke(_state())  # type: ignore[attr-defined]

    assert generator.calls == 1
    assert result["feedback"] == []
    assert result["attempts"][attempt_key("voice", "A", "alto")] == 1
    assert result["voices"][voice_key("A", "alto")].lily_music == GOOD


def test_a_rejected_fragment_is_regenerated_and_then_accepted(tmp_path: Path) -> None:
    generator = ScriptedGenerator([BAD, GOOD])
    renderer = RecordingRenderer([failing_bar_check(line=9), clean()])
    graph = build_voice_graph(_services(generator, renderer, tmp_path), "A", "alto")

    result = graph.invoke(_state())  # type: ignore[attr-defined]

    assert generator.calls == 2
    assert result["feedback"] == []
    assert result["voices"][voice_key("A", "alto")].lily_music == GOOD


def test_the_regeneration_sees_the_rejected_fragment_and_its_feedback(
    tmp_path: Path,
) -> None:
    """A repair prompt needs both — the failing music and the rehearsal note
    about it — because minimal repair preserves accepted material (docs/04)."""
    generator = ScriptedGenerator([BAD, GOOD])
    renderer = RecordingRenderer([failing_bar_check(line=9), clean()])
    graph = build_voice_graph(_services(generator, renderer, tmp_path), "A", "alto")

    graph.invoke(_state())  # type: ignore[attr-defined]

    first, second = generator.contexts
    assert not first.is_regeneration
    assert second.is_regeneration
    assert second.rejected is not None
    assert second.rejected.lily_music == BAD
    assert second.feedback
    assert "bar 1" in second.feedback[0].message


def test_each_attempt_spends_the_budget_for_its_own_loop_key(tmp_path: Path) -> None:
    generator = ScriptedGenerator([BAD, BAD, GOOD])
    renderer = RecordingRenderer(
        [failing_bar_check(line=9), failing_bar_check(line=9), clean()]
    )
    graph = build_voice_graph(_services(generator, renderer, tmp_path), "A", "alto")

    result = graph.invoke(_state())  # type: ignore[attr-defined]

    assert result["attempts"] == {attempt_key("voice", "A", "alto"): 3}


def test_a_rewrite_that_changes_nothing_forfeits_its_copy(tmp_path: Path) -> None:
    """Shown its rejected text under "change as little as possible", the lite
    tier reproduces it nearly verbatim — mistake included; the orchestra run
    burned three ~1400-token identical rewrites this way. When a full
    rewrite's validation feedback carries exactly the fingerprints it was
    shown, the next attempt goes from scratch: the lesson is kept, the
    copyable text is not (docs/04's "regeneration from scratch", finally
    literal)."""
    from cadenzra.app.compose import ComposeServices, _voice_to_convergence

    two_bars = f"{GOOD} {GOOD}"  # bar-count mismatch: not bar-scoped, no patching
    generator = ScriptedGenerator([two_bars, two_bars, GOOD])
    services = ComposeServices(
        generator=generator,
        renderer=RecordingRenderer(),
        workdir=tmp_path,
        budgets=RetryBudgets(),
        synthesizer=None,  # type: ignore[arg-type]
        output_dir=tmp_path,
    )

    part = _voice_to_convergence(_state(), services, SECTION, "alto")

    first, second, third = generator.contexts
    assert second.rejected is not None, "one minimal-repair chance with the text"
    assert third.rejected is None, "an unchanged rejection forfeits the copy"
    assert third.feedback, "the lesson still reaches the regeneration"
    assert part.lily_music == GOOD


def test_an_exhausted_budget_fails_loudly_with_its_evidence(tmp_path: Path) -> None:
    """The pipeline never completes by degrading the music: a stubborn part
    ends the run, naming what failed and why (docs/02, docs/08 principle 4)."""
    generator = ScriptedGenerator([BAD])
    renderer = RecordingRenderer([failing_bar_check(line=9)])
    graph = build_voice_graph(
        _services(generator, renderer, tmp_path, voice_budget=2), "A", "alto"
    )

    with pytest.raises(BudgetExhaustedError) as caught:
        graph.invoke(_state())  # type: ignore[attr-defined]

    error = caught.value
    assert error.loop_key == attempt_key("voice", "A", "alto")
    assert error.attempts == 2
    assert "alto" in str(error)
    assert "bar 1" in str(error)


def test_superseded_feedback_is_cleared_when_its_target_regenerates(
    tmp_path: Path,
) -> None:
    """Only current, unresolved feedback lives in state; history goes to the
    run log (docs/05). Feedback for *other* units must survive untouched."""
    stale = FeedbackItem(
        source="validate_voice",
        level="voice",
        section_id="A",
        voice_id="alto",
        message="an old complaint about the alto",
    )
    other = FeedbackItem(
        source="validate_harmony",
        level="harmony",
        section_id="A",
        message="an unrelated harmony note",
    )
    graph = build_voice_graph(
        _services(ScriptedGenerator([GOOD]), RecordingRenderer([clean()]), tmp_path),
        "A",
        "alto",
    )

    result = graph.invoke(_state(feedback=[stale, other]))  # type: ignore[attr-defined]

    assert result["feedback"] == [other]


def test_the_generator_receives_the_musician_facing_context(tmp_path: Path) -> None:
    generator = ScriptedGenerator([GOOD])
    graph = build_voice_graph(
        _services(generator, RecordingRenderer([clean()]), tmp_path), "A", "alto"
    )

    graph.invoke(_state())  # type: ignore[attr-defined]

    ctx = generator.contexts[0]
    assert ctx.section.section_id == "A"
    assert ctx.voice.voice_id == "alto"
    assert ctx.section.meter.surface_string() == "7/8 (2+2+3)"


def test_a_malformed_artifact_is_a_rejection_not_the_end_of_the_run() -> None:
    """A model that returns an unparseable plan should be told what was wrong
    and asked again — ending the run over it wastes an entire budget on
    something the next attempt could fix (docs/05)."""
    from cadenzra.app.pipeline import _converge
    from cadenzra.common.errors import LLMOutputError

    seen: list[list[str]] = []
    attempts = {"n": 0}

    def generate(feedback: list[FeedbackItem]) -> str:
        seen.append([item.message for item in feedback])
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise LLMOutputError("a 'riff' entry at bar 0, outside its 5 bars")
        return "a good plan"

    result = _converge(
        generate,
        lambda candidate: [],
        budget=3,
        loop_key="structure",
        what="the plan",
    )

    assert result == "a good plan"
    # The parser's own words reached the retry, rather than a paraphrase.
    assert "bar 0" in seen[1][0]


def test_repaired_voices_see_each_other_not_a_stale_snapshot() -> None:
    """Rewriting every named voice against the same snapshot means each avoids
    the others' *old* music, and the new pair can be exactly as parallel.
    Measured on a double fugue, a repair loop went 239 violations, then 48,
    then 48 again, and gave up."""
    from pathlib import Path

    from cadenzra.app.compose import ComposeServices, _rewrite_voices
    from cadenzra.app.config import RetryBudgets
    from cadenzra.model.state import PipelineState, voice_key
    from cadenzra.model.style import StylePack
    from cadenzra.model.voice import VoicePart

    seen: list[dict[str, str]] = []

    class _Recorder:
        """Writes a new line, and records what siblings it was shown."""

        def generate_voice(self, ctx: object) -> VoicePart:
            seen.append(dict(ctx.siblings))  # type: ignore[attr-defined]
            voice_id = ctx.voice.voice_id  # type: ignore[attr-defined]
            # Valid music, so the per-voice validator passes and the test is
            # about what the repair *saw*, not about notation.
            return VoicePart(
                section_id=ctx.section.section_id,  # type: ignore[attr-defined]
                voice_id=voice_id,
                lily_music=f"NEW {GOOD}" if voice_id == "soprano" else GOOD,
            )

        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"unexpected call to {name}")

    soprano = ALTO.model_copy(update={"voice_id": "soprano"})
    section = SECTION.model_copy(update={"active_voices": ["soprano", "alto"]})
    state = PipelineState(
        spec=PieceSpec(
            title="T",
            style_prompt="s",
            voices=[soprano, ALTO],
            meters_allowed=[SEVEN_EIGHT],
            target_minutes=1.0,
        ),
        style=StylePack(),
        structure=StructurePlan(sections=[section]),
        voices={
            voice_key("A", "soprano"): VoicePart(
                section_id="A", voice_id="soprano", lily_music="OLD-soprano"
            ),
            voice_key("A", "alto"): VoicePart(
                section_id="A", voice_id="alto", lily_music="OLD-alto"
            ),
        },
    )
    services = ComposeServices(
        generator=_Recorder(),  # type: ignore[arg-type]
        renderer=RecordingRenderer([clean()]),
        workdir=Path("/tmp/unused"),
        budgets=RetryBudgets(),
        synthesizer=None,  # type: ignore[arg-type]
        output_dir=Path("/tmp/unused"),
    )
    note_s = FeedbackItem(
        source="validate_section", level="section", section_id="A",
        voice_id="soprano", message="parallel octaves with alto",
    )
    note_a = note_s.model_copy(update={"voice_id": "alto"})

    _rewrite_voices(
        state,
        services,
        [note_s, note_a],
        {("A", "soprano"): [note_s], ("A", "alto"): [note_a]},
    )

    assert len(seen) == 2
    # The first repair sees the other voice as it stands; the second sees the
    # first one's *new* line, which is the whole point.
    assert seen[0] == {"alto": "OLD-alto"}
    assert seen[1] == {"soprano": f"NEW {GOOD}"}
