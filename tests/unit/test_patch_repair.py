"""Patch repair: rewrite the flagged bars, splice deterministically.

A repair used to regenerate the whole part — full output, full thinking, and
license to break prescribed bars while "fixing" flagged ones. The patch
surface offers only the editable bars; the splice is pure text with the same
token semantics as `count_bar_checks`, because a second, divergent notion of
"bar" is how off-by-one repairs are born.
"""

from fractions import Fraction
from pathlib import Path

import pytest

from cadenzra.app.compose import ComposeServices, _voice_to_convergence
from cadenzra.app.config import RetryBudgets
from cadenzra.common.errors import LLMOutputError
from cadenzra.llm.parsers.patch import parse_bar_patch
from cadenzra.llm.prompts.patch import build_patch_prompt
from cadenzra.llm.schemas.patch import rewrite_bars_schema
from cadenzra.model.contexts import PatchContext
from cadenzra.model.feedback import FeedbackItem
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
from cadenzra.notation.scaffold import count_bar_checks, splice_bars, split_bars
from tests.fakes.generator import ScriptedGenerator
from tests.fakes.renderer import RecordingRenderer, clean, failing_bar_check

# --- the splice ------------------------------------------------------------

THREE_BARS = "c'4 d'4 e'4 f'4 |\ng'4 a'4 b'4 c''4 |\nc''1 |\n"


def test_split_bars_round_trips_exactly() -> None:
    bars = split_bars(THREE_BARS)

    assert len(bars) == count_bar_checks(THREE_BARS) == 3
    assert "".join(bars) == THREE_BARS


def test_split_bars_honors_quoted_pipes_and_doubles() -> None:
    tricky = 'c\'2 \\bar "|:" c\'2 |\nd\'1 ||\n'

    bars = split_bars(tricky)

    assert len(bars) == count_bar_checks(tricky) == 2
    assert "".join(bars) == tricky


def test_trailing_text_after_the_last_check_stays_with_the_last_bar() -> None:
    dangling = "c'1 |\nd'1 | % a comment after the last barline"

    bars = split_bars(dangling)

    assert "".join(bars) == dangling
    assert "% a comment" in bars[-1]


def test_splice_replaces_exactly_the_named_bars() -> None:
    spliced = splice_bars(THREE_BARS, {2: "g'2 g'2 |"})

    bars = split_bars(spliced)
    assert bars[0] == "c'4 d'4 e'4 f'4 |\n"
    assert bars[1].strip() == "g'2 g'2 |"
    assert bars[2] == "c''1 |\n"


def test_splice_refuses_a_bar_that_does_not_exist() -> None:
    with pytest.raises(ValueError, match="bar 7"):
        splice_bars(THREE_BARS, {7: "c'1 |"})


# --- the schema ------------------------------------------------------------


def test_the_schema_is_constructible_into_a_gemini_tool() -> None:
    """Gemini's schema subset allows `enum` only on strings — an integer enum
    passes every offline check and then crashes `types.Tool` on the first live
    patch (orchestra, 20260810-2036). The vendor type is the only honest
    oracle for what the wire accepts, so it is the one asserted against."""
    from google.genai import types

    tool = rewrite_bars_schema([7, 8, 9, 11, 12])

    types.Tool(function_declarations=[tool])  # type: ignore[list-item]


# --- the parser ------------------------------------------------------------

FOUR_FOUR_BAR = Fraction(1)


def _payload(bar: str, music: str, durations: str) -> dict[str, object]:
    return {
        "replacements": [{"bar": bar, "lily_music": music, "durations": durations}]
    }


def test_the_parser_returns_the_replacements_by_bar() -> None:
    payload = _payload("2", "g'2 g'2 |", "2 2")

    assert parse_bar_patch(payload, [1, 2], bar_length=FOUR_FOUR_BAR) == {2: "g'2 g'2 |"}


def test_a_missing_trailing_bar_check_is_normalized_not_rejected() -> None:
    """Forgiving, never inventive: appending the `|` the contract requires is
    the same normalization the lyric parser applies to `\\lyricmode`."""
    payload = _payload("1", "g'2 g'2", "2 2")

    assert parse_bar_patch(payload, [1], bar_length=FOUR_FOUR_BAR) == {1: "g'2 g'2 |"}


def test_a_declaration_that_does_not_sum_to_the_bar_is_rejected_with_both_numbers() -> None:
    """The copy-reflex forcing function: shown its own 15/16 cadence bar and
    told \"1/16 short\", the live model returned the same durations twice,
    once with a crescendo added. The declaration channel is where the
    arithmetic must be shown, and a copied wrong rhythm cannot pass it —
    the parser does the exact-fraction sum the model cannot be trusted to."""
    payload = _payload("1", "e,4 e,8 e,16 e,8 e,8 e,4 |", "4 8 16 8 8 4")

    with pytest.raises(LLMOutputError, match="15/16") as caught:
        parse_bar_patch(payload, [1], bar_length=FOUR_FOUR_BAR)
    assert "sum" in str(caught.value)


def test_dotted_and_tuplet_durations_declare_their_real_length() -> None:
    payload = _payload(
        "1", "g'8. g'16 \\tuplet 3/2 { g'4 g' g' } g'4 |", "8. 16 1/6 1/6 1/6 4"
    )

    assert parse_bar_patch(payload, [1], bar_length=FOUR_FOUR_BAR) == {
        1: "g'8. g'16 \\tuplet 3/2 { g'4 g' g' } g'4 |"
    }


def test_a_missing_or_unreadable_declaration_is_rejected() -> None:
    with pytest.raises(LLMOutputError, match="durations"):
        parse_bar_patch(
            {"replacements": [{"bar": "1", "lily_music": "g'1 |"}]},
            [1],
            bar_length=FOUR_FOUR_BAR,
        )
    with pytest.raises(LLMOutputError, match="quaver"):
        parse_bar_patch(
            _payload("1", "g'1 |", "quaver quaver"), [1], bar_length=FOUR_FOUR_BAR
        )


def test_a_bar_outside_the_editable_set_is_rejected() -> None:
    payload = _payload("3", "g'1 |", "1")

    with pytest.raises(LLMOutputError, match="bar 3"):
        parse_bar_patch(payload, [1, 2], bar_length=FOUR_FOUR_BAR)


def test_a_non_numeric_bar_is_rejected() -> None:
    payload = _payload("two", "g'1 |", "1")

    with pytest.raises(LLMOutputError, match="two"):
        parse_bar_patch(payload, [1, 2], bar_length=FOUR_FOUR_BAR)


def test_a_multi_bar_replacement_is_rejected() -> None:
    payload = _payload("1", "g'1 | a'1 |", "1")

    with pytest.raises(LLMOutputError, match="exactly one bar"):
        parse_bar_patch(payload, [1], bar_length=FOUR_FOUR_BAR)


def test_an_empty_patch_is_rejected() -> None:
    with pytest.raises(LLMOutputError, match="no replacements"):
        parse_bar_patch({"replacements": []}, [1], bar_length=FOUR_FOUR_BAR)


# --- the prompt (the feedback-reaches-prompt contract, patch edition) ------


def _patch_ctx() -> PatchContext:
    from cadenzra.model.primitives.meter import simple_meter
    from cadenzra.model.primitives.pitch import Pitch
    from cadenzra.model.spec import VoiceSpec
    from cadenzra.model.structure import DynamicsPlan, SectionPlan
    from cadenzra.model.voice import VoicePart

    return PatchContext(
        section=SectionPlan(
            section_id="A",
            bars=3,
            meter=simple_meter(4, 4),
            key="c major",
            tempo_bpm=90,
            texture="imitative",
            dynamics=DynamicsPlan(start="mf"),
            active_voices=["alto", "viola"],
        ),
        voice=VoiceSpec(
            voice_id="alto",
            kind="vocal",
            range_low=Pitch(step="G", octave=3),
            range_high=Pitch(step="C", octave=5),
            midi_program=52,
        ),
        skeleton=None,
        part=VoicePart(section_id="A", voice_id="alto", lily_music=THREE_BARS),
        editable_bars=(2,),
        feedback=[
            FeedbackItem(
                source="validate_section",
                level="section",
                section_id="A",
                voice_id="alto",
                message="alto and viola move in parallel octaves into bar 2, beat 1",
            )
        ],
        siblings={"viola": "e'4 f'4 g'4 a'4 |"},
    )


def test_the_patch_prompt_carries_the_feedback_and_the_siblings() -> None:
    prompt = build_patch_prompt(_patch_ctx())

    assert "parallel octaves into bar 2" in prompt
    assert "e'4 f'4 g'4 a'4" in prompt, "the line it must fit against is shown"
    assert "only" in prompt.lower() and "bar 2" in prompt
    assert "1: c'4 d'4 e'4 f'4 |" in prompt, "bars are numbered so 'bar 2' is findable"


def test_the_patch_prompt_never_offers_a_prescribed_bar() -> None:
    prompt = build_patch_prompt(_patch_ctx())

    assert "bars 1" not in prompt.lower().replace("bars 1, 2, 3", "")
    assert "Rewrite only bar 2" in prompt


# --- the repair loop -------------------------------------------------------



SEVEN_EIGHT = simple_meter(7, 8, [2, 2, 3])
ALTO = VoiceSpec(
    voice_id="alto",
    kind="vocal",
    range_low=Pitch(step="G", octave=3),
    range_high=Pitch(step="C", octave=5),
    midi_program=52,
)
GOOD = "a'8 a' b' b' c''4. |"
BAD = "a'8 a' b' b' c''4 |"


def _loop_section(*entries: MaterialEntry) -> SectionPlan:
    return SectionPlan(
        section_id="A",
        bars=1,
        meter=SEVEN_EIGHT,
        key="d minor",
        tempo_bpm=96,
        texture="imitative",
        dynamics=DynamicsPlan(start="mf"),
        active_voices=["alto"],
        material=list(entries),
    )


def _loop_state(section: SectionPlan, *, motifs: MotifLibrary | None = None) -> PipelineState:
    return PipelineState(
        spec=PieceSpec(
            title="T",
            style_prompt="s",
            voices=[ALTO],
            meters_allowed=[SEVEN_EIGHT],
            target_minutes=1.0,
        ),
        style=StylePack(),
        structure=StructurePlan(sections=[section]),
        motifs=motifs,
        voices={voice_key("A", "alto"): VoicePart(section_id="A", voice_id="alto", lily_music=BAD)},
    )


def _loop_services(
    generator: ScriptedGenerator,
    renderer: RecordingRenderer,
    tmp_path: Path,
    *,
    budgets: RetryBudgets | None = None,
) -> ComposeServices:
    return ComposeServices(
        generator=generator,
        renderer=renderer,
        workdir=tmp_path,
        budgets=budgets or RetryBudgets(),
        synthesizer=None,  # type: ignore[arg-type]
        output_dir=tmp_path,
    )


def _bar_scoped_item() -> FeedbackItem:
    return FeedbackItem(
        source="validate_section",
        level="section",
        section_id="A",
        voice_id="alto",
        location=Fraction(0),
        kind="parallels",
        message="alto and viola move in parallel octaves into bar 1, beat 1",
    )


def test_bar_scoped_feedback_repairs_by_patch_not_rewrite(tmp_path: Path) -> None:
    generator = ScriptedGenerator(patches=[{1: GOOD}])
    services = _loop_services(generator, RecordingRenderer([clean()]), tmp_path)
    section = _loop_section()

    part = _voice_to_convergence(
        _loop_state(section), services, section, "alto", prior=[_bar_scoped_item()]
    )

    assert len(generator.patch_contexts) == 1
    assert generator.calls == 0, "no full rewrite happened"
    assert part.lily_music.strip() == GOOD
    assert generator.patch_contexts[0].editable_bars == (1,)


def test_a_prescribed_bar_is_never_offered_to_a_patch(tmp_path: Path) -> None:
    """The flagged bar is the entry bar, so the patch surface is empty and the
    loop goes straight to a full rewrite — which the entry check still guards."""
    motifs = MotifLibrary(
        motifs={"m": Motif(motif_id="m", role="subject", lily_music=GOOD)}
    )
    section = _loop_section(
        MaterialEntry(motif_id="m", voice_id="alto", bar=1, relation="exact")
    )
    generator = ScriptedGenerator([GOOD])
    services = _loop_services(generator, RecordingRenderer([clean()]), tmp_path)

    _voice_to_convergence(
        _loop_state(section, motifs=motifs),
        services,
        section,
        "alto",
        prior=[_bar_scoped_item()],
    )

    assert generator.patch_contexts == []
    assert generator.calls == 1


def test_two_failed_patches_fall_back_to_full_regeneration(tmp_path: Path) -> None:
    """docs/04: "regeneration from scratch is the fallback when repair fails"
    — promised, never implemented until now."""
    generator = ScriptedGenerator([GOOD], patches=[{1: BAD}, {1: BAD}])
    renderer = RecordingRenderer(
        [failing_bar_check(line=9), failing_bar_check(line=9), clean()]
    )
    services = _loop_services(generator, renderer, tmp_path)
    section = _loop_section()

    part = _voice_to_convergence(
        _loop_state(section), services, section, "alto", prior=[_bar_scoped_item()]
    )

    assert len(generator.patch_contexts) == 2
    assert generator.calls == 1, "the third attempt was the full rewrite"
    assert part.lily_music == GOOD


def test_a_patch_that_reveals_a_masked_bar_costs_no_attempt(tmp_path: Path) -> None:
    """LilyPond reports only the *first* failed bar check per compile, so a
    part with several short bars is discovered one bar per compile. A patch
    can only touch the bars it was offered — when the next compile flags a
    bar it was never offered, that bar was already broken and merely masked.
    Revealing it is progress, not this patch's failure, and must not consume
    the retry budget: here three latent bars converge under a budget of 2.
    (Live: orchestra's flute burned 3 attempts on bars 9, 10, 11 of the same
    kind, each patch correct, and the run died anyway.)"""
    bar2, bar3 = "d'8 d' e' e' f'4. |", "g'8 g' a' a' b'4. |"
    first = f"{GOOD} {bar2} {bar3}"
    fix2, fix3 = "d'4. d'2 |", "g'4. g'2 |"
    spliced = splice_bars(first, {2: fix2})
    section = _loop_section().model_copy(update={"bars": 3})
    generator = ScriptedGenerator([first], patches=[{2: fix2}, {3: fix3}])
    renderer = RecordingRenderer(
        [
            failing_bar_check(line=9, column=first.index("d'") + 1),
            failing_bar_check(line=9, column=spliced.index("g'") + 1),
            clean(),
        ]
    )
    services = _loop_services(
        generator, renderer, tmp_path, budgets=RetryBudgets(voice=2)
    )

    part = _voice_to_convergence(_loop_state(section), services, section, "alto")

    assert generator.calls == 1, "one full write; every repair was a patch"
    assert len(generator.patch_contexts) == 2
    assert part.lily_music == splice_bars(spliced, {3: fix3})


def test_a_compile_failure_is_never_patched(tmp_path: Path) -> None:
    """A part that does not compile has no trustworthy bar numbers to patch."""
    item = FeedbackItem(
        source="validate_voice",
        level="voice",
        section_id="A",
        voice_id="alto",
        message="the part does not compile: not a note name: me",
    )
    generator = ScriptedGenerator([GOOD])
    services = _loop_services(generator, RecordingRenderer([clean()]), tmp_path)
    section = _loop_section()

    _voice_to_convergence(
        _loop_state(section), services, section, "alto", prior=[item]
    )

    assert generator.patch_contexts == []
    assert generator.calls == 1
