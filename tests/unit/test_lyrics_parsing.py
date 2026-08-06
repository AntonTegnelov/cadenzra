"""Lyric lines arrive as lyricmode text and come inward as tokens.

The surface is forgiving and the system is strict underneath (docs/03): a
writer may wrap the block, mirror barlines in, or hand back a bare string, and
what reaches state is the same either way.
"""

import pytest

from cadenzra.common.errors import LLMOutputError
from cadenzra.llm.parsers.lyrics import (
    parse_device_observations,
    parse_lyric_plan,
    parse_section_lyrics,
    render_lyricmode,
    tokenize_line,
)
from cadenzra.model.primitives.meter import simple_meter
from cadenzra.model.structure import DynamicsPlan, SectionPlan, StructurePlan

PLAN = StructurePlan(
    sections=[
        SectionPlan(
            section_id="A",
            bars=4,
            meter=simple_meter(4, 4),
            key="d minor",
            tempo_bpm=90,
            texture="homophonic",
            dynamics=DynamicsPlan(start="mp"),
            active_voices=["soprano"],
        ),
        SectionPlan(
            section_id="B",
            bars=4,
            meter=simple_meter(4, 4),
            key="d minor",
            tempo_bpm=90,
            texture="homophonic",
            dynamics=DynamicsPlan(start="mp"),
            active_voices=["soprano"],
        ),
    ]
)


def test_a_line_becomes_its_tokens() -> None:
    line = tokenize_line("sha -- dow on the wa -- ter __")

    assert line.tokens == ["sha", "--", "dow", "on", "the", "wa", "--", "ter", "__"]
    assert line.words == ["shadow", "on", "the", "water"]
    assert line.syllable_count == 6


def test_barlines_are_stripped_from_lyrics() -> None:
    """Inside `\\lyricmode` a `|` is a bar check. A writer mirroring the music's
    barlines writes checks that pass in a scaffold and fail after assembly."""
    line = tokenize_line("light | falls | slow")

    assert "|" not in line.tokens
    assert line.words == ["light", "falls", "slow"]


def test_a_wrapped_block_is_accepted() -> None:
    line = tokenize_line("\\lyricmode { one two three }")

    assert line.words == ["one", "two", "three"]


def test_the_rendered_block_is_ours_not_the_models() -> None:
    """Rendering here rather than asking for it means the block is always
    well-formed whatever came back."""
    lines = [tokenize_line("sha -- dow"), tokenize_line("falls __")]

    assert render_lyricmode(lines) == "\\lyricmode { sha -- dow falls __ }"


def test_every_singing_voice_must_have_words() -> None:
    payload = {"voices": [{"voice_id": "soprano", "lines": ["one two"]}]}

    with pytest.raises(LLMOutputError, match="alto"):
        parse_section_lyrics(payload, section_id="A", voice_ids=["soprano", "alto"])


def test_words_for_a_voice_that_does_not_sing_are_rejected() -> None:
    payload = {"voices": [{"voice_id": "tuba", "lines": ["one two"]}]}

    with pytest.raises(LLMOutputError, match="tuba"):
        parse_section_lyrics(payload, section_id="A", voice_ids=["soprano"])


def test_empty_lyrics_are_rejected() -> None:
    payload = {"voices": [{"voice_id": "soprano", "lines": ["", "   "]}]}

    with pytest.raises(LLMOutputError, match="empty"):
        parse_section_lyrics(payload, section_id="A", voice_ids=["soprano"])


def test_voices_come_back_in_the_order_they_were_asked_for() -> None:
    payload = {
        "voices": [
            {"voice_id": "alto", "lines": ["low words"]},
            {"voice_id": "soprano", "lines": ["high words"]},
        ]
    }

    lyrics = parse_section_lyrics(
        payload, section_id="A", voice_ids=["soprano", "alto"]
    )

    assert [voice.voice_id for voice in lyrics.voices] == ["soprano", "alto"]


def test_a_plan_naming_a_section_that_does_not_exist_is_rejected() -> None:
    payload = {
        "story": "a story",
        "directives": [
            {"section_id": "Z", "story_beat": "something", "relationship": "unison"}
        ],
    }

    with pytest.raises(LLMOutputError, match="'Z'"):
        parse_lyric_plan(payload, PLAN, language="English")


def test_an_unknown_device_is_dropped_rather_than_failing_the_plan() -> None:
    """A model reaching for a device we do not name is not a malformed answer;
    the vocabulary is the contract, so anything outside it simply is not one."""
    payload = {
        "story": "a story",
        "directives": [
            {
                "section_id": "A",
                "story_beat": "opening",
                "relationship": "unison",
                "devices": ["chiasmus", "iambic_pentameter"],
            }
        ],
    }

    plan = parse_lyric_plan(payload, PLAN, language="English")

    assert plan.directives[0].devices == ["chiasmus"]


def test_a_refrain_of_a_section_that_has_not_happened_is_rejected() -> None:
    payload = {
        "story": "a story",
        "directives": [
            {
                "section_id": "A",
                "story_beat": "opening",
                "relationship": "unison",
                "refrain_of": "B",
            },
            {"section_id": "B", "story_beat": "later", "relationship": "unison"},
        ],
    }

    with pytest.raises(LLMOutputError, match="refrain"):
        parse_lyric_plan(payload, PLAN, language="English")


def test_the_language_comes_from_the_spec_not_the_model() -> None:
    """One language for the piece, decided once — the fix for two voices
    singing in different ones (docs/10)."""
    payload = {
        "story": "a story",
        "directives": [
            {"section_id": "A", "story_beat": "opening", "relationship": "unison"}
        ],
    }

    plan = parse_lyric_plan(payload, PLAN, language="Latin")

    assert plan.language == "Latin"


def test_observations_survive_a_loose_device_name() -> None:
    payload = {
        "observations": [
            {"device": "Objective Correlative", "lines": [1, 2], "evidence": "the rain"}
        ]
    }

    (observation,) = parse_device_observations(payload)

    assert observation.device == "objective_correlative"
    assert observation.lines == [1, 2]


def test_no_observations_is_a_fine_answer() -> None:
    assert parse_device_observations({"observations": []}) == []
    assert parse_device_observations({}) == []
