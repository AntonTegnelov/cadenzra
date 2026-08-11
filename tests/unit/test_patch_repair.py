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
from cadenzra.verification.midi_analysis import NoteEvent
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

FOUR_FOUR = simple_meter(4, 4)


def _payload(bar: str, music: str, durations: str) -> dict[str, object]:
    return {
        "replacements": [{"bar": bar, "lily_music": music, "durations": durations}]
    }


def test_the_parser_returns_the_replacements_by_bar() -> None:
    payload = _payload("2", "g'2 g'2 |", "2 2")

    assert parse_bar_patch(payload, [1, 2], meter=FOUR_FOUR) == {2: "g'2 g'2 |"}


def test_a_missing_trailing_bar_check_is_normalized_not_rejected() -> None:
    """Forgiving, never inventive: appending the `|` the contract requires is
    the same normalization the lyric parser applies to `\\lyricmode`."""
    payload = _payload("1", "g'2 g'2", "2 2")

    assert parse_bar_patch(payload, [1], meter=FOUR_FOUR) == {1: "g'2 g'2 |"}


def test_a_declaration_that_does_not_sum_to_the_bar_is_rejected_with_both_numbers() -> None:
    """The copy-reflex forcing function: shown its own 15/16 cadence bar and
    told \"1/16 short\", the live model returned the same durations twice,
    once with a crescendo added. The declaration channel is where the
    arithmetic must be shown, and a copied wrong rhythm cannot pass it —
    the parser does the exact-fraction sum the model cannot be trusted to."""
    payload = _payload("1", "e,4 e,8 e,16 e,8 e,8 e,4 |", "4 8 16 8 8 4")

    with pytest.raises(LLMOutputError, match="15/16") as caught:
        parse_bar_patch(payload, [1], meter=FOUR_FOUR)
    assert "sum" in str(caught.value)
    assert "r16" in str(caught.value), (
        "the deficit is known exactly, so the rejection names a literal fix — "
        "the live synth declared 15/16 six times against generic advice"
    )


def test_dotted_and_tuplet_durations_declare_their_real_length() -> None:
    payload = _payload(
        "1", "g'8. g'16 \\tuplet 3/2 { g'4 g' g' } g'4 |", "8. 16 1/6 1/6 1/6 4"
    )

    assert parse_bar_patch(payload, [1], meter=FOUR_FOUR) == {
        1: "g'8. g'16 \\tuplet 3/2 { g'4 g' g' } g'4 |"
    }


def test_a_missing_or_unreadable_declaration_is_rejected() -> None:
    with pytest.raises(LLMOutputError, match="durations"):
        parse_bar_patch(
            {"replacements": [{"bar": "1", "lily_music": "g'1 |"}]},
            [1],
            meter=FOUR_FOUR,
        )
    with pytest.raises(LLMOutputError, match="quaver"):
        parse_bar_patch(
            _payload("1", "g'1 |", "quaver quaver"), [1], meter=FOUR_FOUR
        )


def test_a_bar_outside_the_editable_set_is_rejected() -> None:
    payload = _payload("3", "g'1 |", "1")

    with pytest.raises(LLMOutputError, match="bar 3"):
        parse_bar_patch(payload, [1, 2], meter=FOUR_FOUR)


def test_a_non_numeric_bar_is_rejected() -> None:
    payload = _payload("two", "g'1 |", "1")

    with pytest.raises(LLMOutputError, match="two"):
        parse_bar_patch(payload, [1, 2], meter=FOUR_FOUR)


def test_a_multi_bar_replacement_is_rejected() -> None:
    payload = _payload("1", "g'1 | a'1 |", "1")

    with pytest.raises(LLMOutputError, match="exactly one bar"):
        parse_bar_patch(payload, [1], meter=FOUR_FOUR)


def test_an_empty_patch_is_rejected() -> None:
    with pytest.raises(LLMOutputError, match="no replacements"):
        parse_bar_patch({"replacements": []}, [1], meter=FOUR_FOUR)


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


def test_a_malformed_patch_does_not_strike_out_the_patch_path(
    tmp_path: Path,
) -> None:
    """A malformed patch never touched the music — it is a wasted call, not
    evidence that patching cannot fix this part. Counting it as a strike
    funneled live repairs into full rewrites, and a full rewrite of twenty
    bars is where fresh cross-voice violations pour in. The parser's own
    complaint retries the patch; only a patch that was applied and cleared
    nothing is a strike."""
    from cadenzra.common.errors import LLMOutputError

    class _MalformedOnce(ScriptedGenerator):
        raised = False

        def patch_voice(self, ctx: PatchContext) -> dict[int, str]:
            if not self.raised:
                self.raised = True
                raise LLMOutputError(
                    "the replacement for bar 1 declares durations summing to 9/8"
                )
            return super().patch_voice(ctx)

    generator = _MalformedOnce(patches=[{1: BAD}, {1: GOOD}])
    renderer = RecordingRenderer([failing_bar_check(line=9), clean()])
    services = _loop_services(generator, renderer, tmp_path)
    section = _loop_section()

    part = _voice_to_convergence(
        _loop_state(section), services, section, "alto", prior=[_bar_scoped_item()]
    )

    assert generator.calls == 0, "no full rewrite: the patch path stayed alive"
    assert len(generator.patch_contexts) == 2
    assert part.lily_music.strip() == GOOD


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


def test_a_patch_that_clears_some_bars_is_not_a_failed_patch(tmp_path: Path) -> None:
    """Live, a patch legally repaired six of seven offered bars; the one
    stubborn bar counted it as a failure, a second stubborn cycle hit
    _PATCH_ATTEMPTS, and the fallback full rewrite threw all six repairs
    away and reinstated the broken groove template everywhere. Partial
    progress keeps the patching path alive — only a patch that clears
    nothing it was offered is a strike."""
    from cadenzra.model.primitives.time import offset_of

    fix1, fix2 = "g'4. g'2 |", "e'4. e'2 |"
    still_bad = "d'8 d' e' e' f'4 |"
    first = f"{BAD} {BAD}"
    section = _loop_section().model_copy(update={"bars": 2})
    state = _loop_state(section).model_copy(
        update={
            "voices": {
                voice_key("A", "alto"): VoicePart(
                    section_id="A", voice_id="alto", lily_music=first
                )
            }
        }
    )
    after_one = splice_bars(first, {1: fix1, 2: still_bad})
    generator = ScriptedGenerator(
        patches=[{1: fix1, 2: still_bad}, {2: still_bad}, {2: fix2}]
    )
    renderer = RecordingRenderer(
        [
            failing_bar_check(line=9, column=after_one.index("d'") + 1),
            failing_bar_check(line=9, column=after_one.index("d'") + 1),
            clean(),
        ]
    )
    services = _loop_services(generator, renderer, tmp_path)
    prior = [
        _bar_scoped_item(),
        _bar_scoped_item().model_copy(
            update={"location": offset_of(2, 1, SEVEN_EIGHT)}
        ),
    ]

    part = _voice_to_convergence(state, services, section, "alto", prior=prior)

    assert generator.calls == 0, "no full rewrite ever happened"
    assert len(generator.patch_contexts) == 3
    assert part.lily_music == splice_bars(after_one, {2: fix2})


def test_a_patch_prompt_keeps_only_feedback_about_offered_bars(
    tmp_path: Path,
) -> None:
    """The double-fugue forensics: the patch prompt quoted complaints about
    bars it refused to offer, steering every patch at music it could not
    touch. Feedback about a bar outside the offer belongs to some other
    repair; only the loop's *prompt* is filtered — the loop itself keeps the
    full list, because convergence is measured against everything."""
    from cadenzra.model.primitives.time import offset_of

    motifs = MotifLibrary(
        motifs={"m": Motif(motif_id="m", role="subject", lily_music=GOOD)}
    )
    section = _loop_section(
        MaterialEntry(motif_id="m", voice_id="alto", bar=1, relation="exact")
    ).model_copy(update={"bars": 2})
    first = f"{GOOD} {BAD}"
    state = _loop_state(section, motifs=motifs).model_copy(
        update={
            "voices": {
                voice_key("A", "alto"): VoicePart(
                    section_id="A", voice_id="alto", lily_music=first
                )
            }
        }
    )
    prescribed_bar_item = _bar_scoped_item()
    free_bar_item = _bar_scoped_item().model_copy(
        update={
            "location": offset_of(2, 1, SEVEN_EIGHT),
            "message": "alto and viola move in parallel octaves into bar 2, beat 1",
        }
    )
    generator = ScriptedGenerator(patches=[{2: GOOD}])
    services = _loop_services(generator, RecordingRenderer([clean()]), tmp_path)

    _voice_to_convergence(
        state,
        services,
        section,
        "alto",
        prior=[prescribed_bar_item, free_bar_item],
    )

    assert len(generator.patch_contexts) == 1
    ctx = generator.patch_contexts[0]
    assert ctx.editable_bars == (2,)
    assert [item.message for item in ctx.feedback] == [free_bar_item.message], (
        "the complaint about the prescribed bar 1 is not the patch's business"
    )


def test_feedback_inside_a_prescribed_entry_carries_the_prescription(
    tmp_path: Path,
) -> None:
    """The other half of the trap: a range item landing inside the entry span
    told the rewrite to move notes the entry check pins. When the entry is
    prescribed, the rehearsal note now hands the answer over — the exact bars
    to write — instead of leaving two contradictory orders standing."""
    from fractions import Fraction as F

    from cadenzra.verification.midi_analysis import NoteEvent

    def _note(pitch: int, onset: F, duration: F) -> NoteEvent:
        return NoteEvent(
            midi_pitch=pitch, onset=onset, duration=duration, velocity=80, channel=0
        )

    motifs = MotifLibrary(
        motifs={"m": Motif(motif_id="m", role="subject", lily_music=GOOD)}
    )
    events = [
        _note(69, F(0), F(1, 8)),
        _note(69, F(1, 8), F(1, 8)),
        _note(71, F(2, 8), F(1, 8)),
        _note(71, F(3, 8), F(1, 8)),
        _note(72, F(4, 8), F(3, 8)),
    ]
    section = _loop_section(
        MaterialEntry(motif_id="m", voice_id="alto", bar=1, relation="exact")
    )
    range_item = FeedbackItem(
        source="validate_voice",
        level="voice",
        section_id="A",
        voice_id="alto",
        location=Fraction(0),
        kind="range",
        message="1 note in bar 1 sits below the range floor",
    )
    unplaced_item = FeedbackItem(
        source="validate_section",
        level="section",
        section_id="A",
        voice_id="alto",
        message="the section never reaches its dynamic target",
    )
    generator = ScriptedGenerator([GOOD])
    services = _loop_services(generator, RecordingRenderer([clean()]), tmp_path)

    _voice_to_convergence(
        state := _loop_state(section, motifs=motifs),
        services,
        section,
        "alto",
        prior=[range_item, unplaced_item],
        motif_events={"m": events},
    )
    del state

    ctx = generator.contexts[0]
    (instruction,) = ctx.materials
    assert instruction.prescribed_lily == "a'8 a'8 b'8 b'8 c''4. |"
    decorated, untouched = ctx.feedback
    assert "write it exactly as" in decorated.message
    assert "a'8 a'8 b'8 b'8 c''4. |" in decorated.message
    assert untouched.message == unplaced_item.message, (
        "an item with no bar to pin cannot be attributed to the entry"
    )


def _events_for(pitches_and_durations: list[tuple[int, str]]) -> list[NoteEvent]:
    from fractions import Fraction as F

    events = []
    cursor = F(0)
    for pitch, dur in pitches_and_durations:
        length = {"8": F(1, 8), "4": F(1, 4), "4.": F(3, 8), "2": F(1, 2), "1": F(1)}[
            dur
        ]
        events.append(
            NoteEvent(
                midi_pitch=pitch, onset=cursor, duration=length, velocity=80, channel=0
            )
        )
        cursor += length
    return events


def test_a_rewrite_cannot_break_a_prescribed_entry(tmp_path: Path) -> None:
    """The named escalation, now earned: with the prescription in the prompt,
    a live rewrite under a wall of cross-voice complaints still paraphrased
    its entry — three entries broken in one sweep, and every downstream
    guarantee (the pinned grid, the entry check) fell with them. The
    prescribed bars are not the model's to write, so they are not left to
    the model to copy: they are spliced in deterministically."""
    motifs = MotifLibrary(
        motifs={"m": Motif(motif_id="m", role="subject", lily_music=GOOD)}
    )
    events = _events_for([(69, "8"), (69, "8"), (71, "8"), (71, "8"), (72, "4.")])
    section = _loop_section(
        MaterialEntry(motif_id="m", voice_id="alto", bar=1, relation="exact")
    )
    paraphrased = "g'8 g' a' a' b'4. |"
    generator = ScriptedGenerator([paraphrased])
    services = _loop_services(generator, RecordingRenderer([clean()]), tmp_path)

    part = _voice_to_convergence(
        _loop_state(section, motifs=motifs),
        services,
        section,
        "alto",
        motif_events={"m": events},
    )

    assert "a'8 a'8 b'8 b'8 c''4. |" in part.lily_music
    assert "g'8" not in part.lily_music


def test_an_open_final_bar_of_a_prescription_stays_the_models_to_complete(
    tmp_path: Path,
) -> None:
    """Only the complete bars are spliced: a prescription ending mid-bar
    leaves its final bar open for the composer, exactly as the prompt says."""
    motifs = MotifLibrary(
        motifs={"m": Motif(motif_id="m", role="subject", lily_music=f"{GOOD} c''4 |")}
    )
    # One full 7/8 bar, then a lone quarter: the rebar leaves bar 2 open.
    events = _events_for(
        [(69, "8"), (69, "8"), (71, "8"), (71, "8"), (72, "4."), (72, "4")]
    )
    section = _loop_section(
        MaterialEntry(motif_id="m", voice_id="alto", bar=1, relation="exact")
    ).model_copy(update={"bars": 2})
    written = "g'8 g' a' a' b'4. |\nc''4 b'8 a'8 g'4 |"
    generator = ScriptedGenerator([written])
    services = _loop_services(generator, RecordingRenderer([clean()]), tmp_path)

    part = _voice_to_convergence(
        _loop_state(section, motifs=motifs),
        services,
        section,
        "alto",
        motif_events={"m": events},
    )

    assert "a'8 a'8 b'8 b'8 c''4. |" in part.lily_music, "bar 1 is spliced"
    assert "c''4 b'8 a'8 g'4 |" in part.lily_music, "the open bar 2 stays as written"


def test_an_open_prescription_is_decorated_as_a_beginning_not_a_whole(
    tmp_path: Path,
) -> None:
    """A 7/8-of-a-bar prescription decorated with "write it exactly as" beside
    a "bar is 1/8 short" deficit is two contradictory orders — the live viola
    obeyed the wrong one five attempts running. An open prescription is a
    beginning: the decoration must say so and say to complete the bar."""
    from cadenzra.model.primitives.time import offset_of

    motifs = MotifLibrary(
        motifs={"m": Motif(motif_id="m", role="subject", lily_music=f"{GOOD} c''4 |")}
    )
    events = _events_for(
        [(69, "8"), (69, "8"), (71, "8"), (71, "8"), (72, "4."), (72, "4")]
    )
    section = _loop_section(
        MaterialEntry(motif_id="m", voice_id="alto", bar=1, relation="exact")
    ).model_copy(update={"bars": 2})
    short_item = FeedbackItem(
        source="validate_voice",
        level="voice",
        section_id="A",
        voice_id="alto",
        location=offset_of(2, 1, SEVEN_EIGHT),
        kind="meter",
        message="bar 2 does not fill 7/8 (2+2+3); it is 1/2 short",
    )
    generator = ScriptedGenerator([f"{GOOD} c''4 b'8 a'8 g'8 |"])
    services = _loop_services(generator, RecordingRenderer([clean()]), tmp_path)

    _voice_to_convergence(
        _loop_state(section, motifs=motifs).model_copy(
            update={
                "voices": {
                    voice_key("A", "alto"): VoicePart(
                        section_id="A", voice_id="alto", lily_music=f"{GOOD} c''4 |"
                    )
                }
            }
        ),
        services,
        section,
        "alto",
        prior=[short_item],
        motif_events={"m": events},
    )

    ctx = generator.contexts[0]
    (decorated,) = ctx.feedback
    assert "write it exactly as" not in decorated.message
    assert "begin it exactly with" in decorated.message
    assert "complete" in decorated.message


def test_a_sweep_repair_never_falls_back_to_a_full_rewrite(tmp_path: Path) -> None:
    """During a cross-voice sweep every part has already passed its own
    checks, and a full rewrite is where fresh faults pour in — one rewritten
    viola injected twelve, live. When patching strikes out, the repair
    returns the part as it stands; the sweep re-flags what remains and the
    alternating router hands it to the partner voice next time."""
    generator = ScriptedGenerator(patches=[{1: BAD}, {1: BAD}])
    renderer = RecordingRenderer(
        [failing_bar_check(line=9), failing_bar_check(line=9)]
    )
    services = _loop_services(generator, renderer, tmp_path)
    section = _loop_section()

    part = _voice_to_convergence(
        _loop_state(section),
        services,
        section,
        "alto",
        prior=[_bar_scoped_item()],
        patch_only=True,
    )

    assert generator.calls == 0, "no full rewrite, ever, on the sweep path"
    assert len(generator.patch_contexts) == 2
    assert part.lily_music.strip() == BAD, "the part comes back as it stands"


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
