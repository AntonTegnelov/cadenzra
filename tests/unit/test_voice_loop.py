"""Loop mechanics, entirely against fakes.

These assert the machinery the whole pipeline depends on: that feedback routes
back to the node that can fix it, that budgets decrement per loop key, that
exhaustion fails loudly with its evidence, and that superseded feedback is
cleared when its target regenerates (docs/09).
"""

from fractions import Fraction
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


def test_the_previous_tail_arrives_with_the_meter_it_was_written_in(
    tmp_path: Path,
) -> None:
    """The tail's meter is the *source* section's, found by the same walk that
    finds the tail — a voice silent in the section just before must get the
    meter of the section its tail actually came from."""
    from cadenzra.app.compose import ComposeServices, _voice_to_convergence
    from cadenzra.model.voice import VoicePart

    four_four = simple_meter(4, 4)
    first = SECTION.model_copy(update={"section_id": "A", "meter": four_four})
    silent = SECTION.model_copy(update={"section_id": "B", "active_voices": []})
    last = SECTION.model_copy(update={"section_id": "C"})
    state = _state(
        spec=PieceSpec(
            title="T",
            style_prompt="s",
            voices=[ALTO],
            meters_allowed=[four_four, SEVEN_EIGHT],
            target_minutes=1.0,
        ),
        structure=StructurePlan(sections=[first, silent, last]),
        voices={
            voice_key("A", "alto"): VoicePart(
                section_id="A", voice_id="alto", lily_music="c'4 d'4 e'4 f'4 |"
            )
        },
    )
    generator = ScriptedGenerator([GOOD])
    services = ComposeServices(
        generator=generator,
        renderer=RecordingRenderer([clean()]),
        workdir=tmp_path,
        budgets=RetryBudgets(),
        synthesizer=None,  # type: ignore[arg-type]
        output_dir=tmp_path,
    )

    _voice_to_convergence(state, services, last, "alto")

    ctx = generator.contexts[0]
    assert ctx.previous_tail == "c'4 d'4 e'4 f'4 |"
    assert ctx.previous_meter == four_four


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


def test_the_third_attempt_sees_every_fault_the_loop_has_raised() -> None:
    """The design principle's cumulative half: attempt 2 fixes fault A but
    introduces fault B; if attempt 3 sees only B, the model trades A for B
    forever. It must see B to fix and A as a keep-fixed reminder."""
    from fractions import Fraction as F

    from cadenzra.app.pipeline import _converge

    fault_a = FeedbackItem(
        source="validate_harmony",
        level="harmony",
        section_id="A",
        location=F(0),
        kind="gap",
        message="nothing is harmonized in bar 1",
    )
    fault_b = fault_a.model_copy(
        update={"location": F(1), "message": "the chord at bar 2 overlaps"}
    )
    seen: list[list[str]] = []

    def generate(feedback: list[FeedbackItem]) -> int:
        seen.append([item.message for item in feedback])
        return len(seen)

    def validate(candidate: int) -> list[FeedbackItem]:
        return {1: [fault_a], 2: [fault_b], 3: []}[candidate]

    _converge(generate, validate, budget=4, loop_key="harmony:A", what="the grid")

    third = seen[2]
    assert any("overlaps" in message for message in third), "B is the ask"
    assert any(
        "bar 1" in message and "keep it fixed" in message for message in third
    ), "A rides along as a keep-fixed reminder"


def test_a_voice_repair_carries_its_cleared_faults_forward(
    tmp_path: Path,
) -> None:
    """Same contract inside the voice loop, patch edition: the cross-voice
    fault the first patch cleared must still be visible to the second patch
    of the same bar, decorated as already fixed, beside the new fault — or
    the fix for the meter reinstates the parallel."""
    from fractions import Fraction as F

    from cadenzra.app.compose import ComposeServices, _voice_to_convergence
    from cadenzra.model.voice import VoicePart

    parallel = FeedbackItem(
        source="validate_section",
        level="section",
        section_id="A",
        voice_id="alto",
        location=F(0),
        kind="parallels",
        message="alto and viola move in parallel octaves into bar 1, beat 1",
    )
    generator = ScriptedGenerator(patches=[{1: BAD}, {1: GOOD}])
    renderer = RecordingRenderer([failing_bar_check(line=9), clean()])
    services = ComposeServices(
        generator=generator,
        renderer=renderer,
        workdir=tmp_path,
        budgets=RetryBudgets(),
        synthesizer=None,  # type: ignore[arg-type]
        output_dir=tmp_path,
    )
    state = _state(
        voices={
            voice_key("A", "alto"): VoicePart(
                section_id="A", voice_id="alto", lily_music=BAD
            )
        }
    )

    part = _voice_to_convergence(
        state, services, SECTION, "alto", prior=[parallel]
    )

    assert part.lily_music.strip() == GOOD
    second = [item.message for item in generator.patch_contexts[1].feedback]
    assert any("does not fill" in message for message in second), "the new fault"
    assert any(
        "parallel octaves" in message and "keep it fixed" in message
        for message in second
    ), "the cleared parallel rides along on the re-offered bar"


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


def test_alternate_sweeps_hand_a_both_free_fault_to_the_other_voice() -> None:
    """A live loop ground 73 -> 25 -> ... -> 2 -> 2 and died with the same
    two faults routed to the same voice every sweep — the fixed anchor means
    a mover that cannot clear a fault retries it forever while its partner
    never gets a turn. On alternate sweeps the other free voice moves; a
    fault with only one free voice keeps its only possible target."""
    from cadenzra.app.compose import _swap_both_free

    both_free = FeedbackItem(
        source="validate_section",
        level="section",
        section_id="A",
        voice_id="soprano",
        kind="parallels",
        voices=("bass", "soprano"),
        routing="both-free",
        message="bass and soprano move in parallel fifths into bar 2, beat 1",
    )
    pinned_side = both_free.model_copy(
        update={"voice_id": "bass", "routing": "only-free-voice"}
    )

    swapped = _swap_both_free([both_free, pinned_side])

    assert swapped[0].voice_id == "bass", "the other free voice takes a turn"
    assert swapped[1].voice_id == "bass", "a single-target item never swaps"


def test_a_voice_that_cannot_converge_yields_back_to_the_sweep(
    tmp_path: Path,
) -> None:
    """A healthy sweep (148 -> 134 -> 111 live) died because one voice's
    repair ran out of local attempts on noise. One voice's bad dice-run is
    the sweep's problem, not the run's: the old part stays, its violations
    stay on the board for the next sweep, and the plateau guard and section
    budget still end a genuinely stuck loop loudly."""
    from cadenzra.app.compose import ComposeServices, _rewrite_voices
    from cadenzra.model.voice import VoicePart

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
                section_id="A", voice_id="soprano", lily_music=BAD
            ),
            voice_key("A", "alto"): VoicePart(
                section_id="A", voice_id="alto", lily_music=BAD
            ),
        },
    )
    # Every soprano patch comes back malformed — a rejection no retry fixes
    # within its budget; the alto repairs cleanly on its first patch.
    from cadenzra.common.errors import LLMOutputError

    class _SopranoMalformed(ScriptedGenerator):
        def patch_voice(self, ctx: object) -> dict[int, str]:
            if ctx.voice.voice_id == "soprano":  # type: ignore[attr-defined]
                raise LLMOutputError(
                    "the replacement for bar 1 declares durations summing to 9/8"
                )
            return super().patch_voice(ctx)  # type: ignore[arg-type]

    generator = _SopranoMalformed(patches=[{1: GOOD}])
    services = ComposeServices(
        generator=generator,
        renderer=RecordingRenderer([clean()]),
        workdir=tmp_path,
        budgets=RetryBudgets(voice=2),
        synthesizer=None,  # type: ignore[arg-type]
        output_dir=tmp_path,
    )
    note = FeedbackItem(
        source="validate_section",
        level="section",
        section_id="A",
        voice_id="soprano",
        location=Fraction(0),
        kind="parallels",
        message="parallel octaves with the alto into bar 1, beat 1",
    )
    targets = {
        ("A", "soprano"): [note],
        ("A", "alto"): [note.model_copy(update={"voice_id": "alto"})],
    }

    repaired = _rewrite_voices(state, services, list(targets.values())[0], targets)

    assert repaired.voices[voice_key("A", "soprano")].lily_music == BAD, (
        "the exhausted repair keeps the old part for the next sweep"
    )
    assert repaired.voices[voice_key("A", "alto")].lily_music.strip() == GOOD, (
        "the sweep carried on past the exhausted voice"
    )


def test_repaired_voices_see_each_other_not_a_stale_snapshot() -> None:
    """Repairing every named voice against the same snapshot means each
    avoids the others' *old* music, and the new pair can be exactly as
    parallel. Measured on a double fugue, a repair loop went 239 violations,
    then 48, then 48 again, and gave up."""
    from pathlib import Path

    from cadenzra.app.compose import ComposeServices, _rewrite_voices
    from cadenzra.app.config import RetryBudgets
    from cadenzra.model.state import PipelineState, voice_key
    from cadenzra.model.style import StylePack
    from cadenzra.model.voice import VoicePart

    NEW_SOPRANO = "b'8 b' c'' c'' d''4. |"
    seen: list[dict[str, str]] = []

    class _Recorder(ScriptedGenerator):
        """Patches a new line, and records what siblings it was shown."""

        def patch_voice(self, ctx: object) -> dict[int, str]:
            seen.append(dict(ctx.siblings))  # type: ignore[attr-defined]
            voice_id = ctx.voice.voice_id  # type: ignore[attr-defined]
            return {1: NEW_SOPRANO if voice_id == "soprano" else GOOD}

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
                section_id="A", voice_id="soprano", lily_music=BAD
            ),
            voice_key("A", "alto"): VoicePart(
                section_id="A", voice_id="alto", lily_music=BAD
            ),
        },
    )
    services = ComposeServices(
        generator=_Recorder(),
        renderer=RecordingRenderer([clean()]),
        workdir=Path("/tmp/unused"),
        budgets=RetryBudgets(),
        synthesizer=None,  # type: ignore[arg-type]
        output_dir=Path("/tmp/unused"),
    )
    note_s = FeedbackItem(
        source="validate_section",
        level="section",
        section_id="A",
        voice_id="soprano",
        location=Fraction(0),
        kind="parallels",
        message="parallel octaves with alto into bar 1, beat 1",
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
    assert seen[0] == {"alto": BAD}
    assert seen[1] == {"soprano": f"{NEW_SOPRANO}\n"}
