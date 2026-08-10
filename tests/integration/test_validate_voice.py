"""The M1 gate for `validate_voice`, against the real compiler.

Every crafted-bad fragment must be rejected with a correctly targeted,
bar-numbered feedback item; every valid one must be accepted (docs/09). The
assertions check the *contract* — level, ids, and that the message names the
right bar — not the exact prose, which is free to improve.
"""

from pathlib import Path

import pytest

from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.primitives.meter import MeterSpec, MeterTerm, simple_meter
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.spec import VoiceSpec
from cadenzra.model.structure import DynamicsPlan, SectionPlan
from cadenzra.model.voice import TechniqueSpan, VoicePart
from cadenzra.rendering.lilypond import LilypondAdapter
from cadenzra.verification.voice import validate_voice

pytestmark = pytest.mark.integration

SEVEN_EIGHT = simple_meter(7, 8, [2, 2, 3])
FOUR_FOUR = simple_meter(4, 4)
ADDITIVE = MeterSpec(
    terms=[MeterTerm(numerator=3, denominator=4), MeterTerm(numerator=1, denominator=8)]
)

ALTO = VoiceSpec(
    voice_id="alto",
    kind="vocal",
    range_low=Pitch(step="G", octave=3),
    range_high=Pitch(step="C", octave=5),
    midi_program=52,
    lyrics=True,
)


@pytest.fixture(scope="module")
def renderer() -> LilypondAdapter:
    return LilypondAdapter()


def _section(meter: MeterSpec = SEVEN_EIGHT, bars: int = 2) -> SectionPlan:
    return SectionPlan(
        section_id="A",
        bars=bars,
        meter=meter,
        key="d minor",
        tempo_bpm=96,
        texture="homophonic",
        dynamics=DynamicsPlan(start="mf"),
        active_voices=["alto"],
    )


def _check(
    music: str,
    renderer: LilypondAdapter,
    workdir: Path,
    *,
    meter: MeterSpec = SEVEN_EIGHT,
    bars: int = 2,
    lyrics: str | None = None,
    techniques: list[TechniqueSpan] | None = None,
) -> list[FeedbackItem]:
    part = VoicePart(
        section_id="A",
        voice_id="alto",
        lily_music=music,
        lily_lyrics=lyrics,
        techniques=techniques or [],
    )
    return validate_voice(part, ALTO, _section(meter, bars), renderer, workdir)


GOOD_SEVEN_EIGHT = "a'8 a' b' b' c''4. |\ng'8 g' a' a' b'4. |"


def test_a_valid_fragment_is_accepted(renderer: LilypondAdapter, tmp_path: Path) -> None:
    assert _check(GOOD_SEVEN_EIGHT, renderer, tmp_path) == []


def test_an_overfilled_bar_is_rejected_and_names_its_bar(
    renderer: LilypondAdapter, tmp_path: Path
) -> None:
    music = "a'8 a' b' b' c''4. |\ng'8 g' a' a' b' b' b' b' |"

    feedback = _check(music, renderer, tmp_path)

    assert len(feedback) == 1
    item = feedback[0]
    assert item.level == "voice"
    assert item.section_id == "A"
    assert item.voice_id == "alto"
    assert "bar 2" in item.message
    assert "7/8 (2+2+3)" in item.message


def test_an_underfilled_bar_is_rejected(renderer: LilypondAdapter, tmp_path: Path) -> None:
    music = "a'8 a' b' b' c''4. |\ng'8 g' a'4 |"

    feedback = _check(music, renderer, tmp_path)

    assert len(feedback) == 1
    assert "bar 2" in feedback[0].message


def test_a_note_above_the_ceiling_is_rejected_by_name(
    renderer: LilypondAdapter, tmp_path: Path
) -> None:
    music = "a'8 a' b' b' c''4. |\ng'8 g' a' a' e''4. |"

    feedback = _check(music, renderer, tmp_path)

    assert len(feedback) == 1
    assert "E5" in feedback[0].message
    assert "above" in feedback[0].message
    assert "C5" in feedback[0].message
    assert "bar 2" in feedback[0].message


def test_a_note_below_the_floor_is_rejected_by_name(
    renderer: LilypondAdapter, tmp_path: Path
) -> None:
    music = "a'8 a' b' b' c''4. |\nc8 g' a' a' b'4. |"

    feedback = _check(music, renderer, tmp_path)

    assert any("below" in item.message and "G3" in item.message for item in feedback)


def test_a_bar_of_out_of_range_notes_is_one_rehearsal_note(
    renderer: LilypondAdapter, tmp_path: Path
) -> None:
    """A live lite-tier run wrote stratospheric figuration and drew ~80 items,
    one per note, flooding the regeneration prompt — the audit's violation
    inflation, solo edition. A bar of wrong notes is one rehearsal note that
    names the extent, because the prompt is the message's real consumer."""
    music = "a'8 a' b' b' c''4. |\ne''8 f'' g'' a'' b''4. |"

    feedback = _check(music, renderer, tmp_path)

    assert len(feedback) == 1
    (item,) = feedback
    assert "bar 2" in item.message
    assert "5 notes" in item.message
    assert "B5" in item.message, "the farthest offender is named"
    assert "C5" in item.message, "so is the limit"


def test_a_fragment_carrying_structural_commands_is_rejected(
    renderer: LilypondAdapter, tmp_path: Path
) -> None:
    """Structure belongs to the assembler; a fragment that sets its own meter
    cannot be assembled deterministically (docs/03)."""
    music = "\\time 7/8\na'8 a' b' b' c''4. |"

    feedback = _check(music, renderer, tmp_path)

    assert len(feedback) == 1
    assert "\\time" in feedback[0].message


@pytest.mark.parametrize("command", ["\\score {}", "\\clef treble", "\\relative c'"])
def test_every_forbidden_command_is_caught(
    command: str, renderer: LilypondAdapter, tmp_path: Path
) -> None:
    feedback = _check(f"{command}\na'8 a' b' b' c''4. |", renderer, tmp_path)

    assert feedback
    assert all(item.level == "voice" for item in feedback)


def test_a_fragment_that_does_not_compile_is_rejected_with_the_compiler_output(
    renderer: LilypondAdapter, tmp_path: Path
) -> None:
    feedback = _check("a'8 a' b' b' c''4. | { unclosed", renderer, tmp_path)

    assert len(feedback) == 1
    assert "does not compile" in feedback[0].message
    assert feedback[0].evidence
    assert "error" in feedback[0].evidence


def test_a_missing_bar_check_is_itself_a_failure(
    renderer: LilypondAdapter, tmp_path: Path
) -> None:
    """A bar check is what lets the compiler report a bar that does not fill,
    so an omitted one is a hole in the meter validator rather than a cosmetic
    lapse — and it must be caught even when the music happens to add up."""
    music = "a'8 a' b' b' c''4.\ng'8 g' a' a' b'4. |"

    feedback = _check(music, renderer, tmp_path)

    assert len(feedback) == 1
    assert "1 bar check" in feedback[0].message
    assert "2 bars long" in feedback[0].message


def test_nested_tuplets_are_ordinary_lilypond_and_must_pass(
    renderer: LilypondAdapter, tmp_path: Path
) -> None:
    """Tick-rounding in nested tuplets must not false-positive (docs/05)."""
    music = "\\tuplet 3/2 { a'4 b' c'' } \\tuplet 5/4 { a'8 b' c'' b' a' } |"

    assert _check(music, renderer, tmp_path, meter=FOUR_FOUR, bars=1) == []


def test_additive_meters_validate_like_any_other(
    renderer: LilypondAdapter, tmp_path: Path
) -> None:
    good = "a'8 a' b' b' c''4. |"
    bad = "a'8 a' b' b' c''4 |"

    assert _check(good, renderer, tmp_path, meter=ADDITIVE, bars=1) == []
    assert _check(bad, renderer, tmp_path, meter=ADDITIVE, bars=1)


def test_dynamics_and_markup_are_ordinary_lilypond(
    renderer: LilypondAdapter, tmp_path: Path
) -> None:
    music = "a'8\\pp a' b' b' c''4.\\< |\ng'8 g' a' a' b'4.\\ff |"

    assert _check(music, renderer, tmp_path) == []


def test_matching_lyrics_are_accepted(renderer: LilypondAdapter, tmp_path: Path) -> None:
    music = "a'8 a' b' b' c''4. |"
    lyrics = "\\lyricmode { Sing the mea -- sure now }"

    assert _check(music, renderer, tmp_path, bars=1, lyrics=lyrics) == []


def test_a_technique_reaching_past_the_section_is_rejected(
    renderer: LilypondAdapter, tmp_path: Path
) -> None:
    feedback = _check(
        GOOD_SEVEN_EIGHT,
        renderer,
        tmp_path,
        techniques=[TechniqueSpan(technique="whispered", from_bar=1, to_bar=9)],
    )

    assert len(feedback) == 1
    assert "bar 9" in feedback[0].message
    assert "2 bars long" in feedback[0].message


def test_a_technique_inside_the_section_is_accepted(
    renderer: LilypondAdapter, tmp_path: Path
) -> None:
    assert (
        _check(
            GOOD_SEVEN_EIGHT,
            renderer,
            tmp_path,
            techniques=[TechniqueSpan(technique="whispered", from_bar=1, to_bar=2)],
        )
        == []
    )


def test_every_message_reads_like_a_rehearsal_note(
    renderer: LilypondAdapter, tmp_path: Path
) -> None:
    """Feedback is part of the LLM surface: it speaks bars, not offsets, and
    never leaks validator internals (docs/05, docs/08 principle 2)."""
    music = "a'8 a' b' b' c''4. |\ng'8 g' a' a' e'' b' b' b' |"

    feedback = _check(music, renderer, tmp_path)

    assert feedback
    for item in feedback:
        assert "bar " in item.message
        assert "offset" not in item.message
        assert "Fraction" not in item.message
