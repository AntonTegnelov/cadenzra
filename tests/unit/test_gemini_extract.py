"""Pulling the tool call — and the reasoning — out of a response.

A pure function over the SDK's response shape, so it is testable without a
network: the stubs below mimic only the three attributes the walk reads.
"""

from dataclasses import dataclass, field
from typing import Any

import pytest

from cadenzra.common.errors import LLMOutputError
from cadenzra.llm.clients.gemini import _extract


@dataclass
class _Call:
    name: str
    args: dict[str, Any]


@dataclass
class _Part:
    text: str | None = None
    thought: bool = False
    function_call: _Call | None = None


@dataclass
class _Content:
    parts: list[_Part] = field(default_factory=list)


@dataclass
class _Candidate:
    content: _Content


@dataclass
class _Response:
    candidates: list[_Candidate]
    text: str = ""


def _response(parts: list[_Part]) -> Any:
    return _Response(candidates=[_Candidate(content=_Content(parts=parts))])


def test_the_tool_call_arguments_come_back() -> None:
    response = _response([_Part(function_call=_Call("write_part", {"lily_music": "c'1"}))])

    arguments, thoughts = _extract(response, "write_part")

    assert arguments == {"lily_music": "c'1"}
    assert thoughts is None


def test_thought_parts_are_collected() -> None:
    """Reasoning is what makes the narrative log worth reading — a walk that
    only looked for the function call would throw it away."""
    response = _response(
        [
            _Part(text="Seven eighths, grouped 2+2+3.", thought=True),
            _Part(text="So the last beat wants a dotted quarter.", thought=True),
            _Part(function_call=_Call("write_part", {"lily_music": "c'8 d'8 e'4."})),
        ]
    )

    arguments, thoughts = _extract(response, "write_part")

    assert arguments == {"lily_music": "c'8 d'8 e'4."}
    assert thoughts is not None
    assert "2+2+3" in thoughts and "dotted quarter" in thoughts


def test_ordinary_text_is_not_mistaken_for_thinking() -> None:
    response = _response(
        [
            _Part(text="Here is the part.", thought=False),
            _Part(function_call=_Call("write_part", {"lily_music": "c'1"})),
        ]
    )

    _, thoughts = _extract(response, "write_part")

    assert thoughts is None


def test_a_response_with_no_tool_call_raises() -> None:
    response = _response([_Part(text="I would rather describe the piece.")])
    response.text = "I would rather describe the piece."

    with pytest.raises(LLMOutputError, match="without calling write_part"):
        _extract(response, "write_part")


def test_a_call_to_a_different_tool_does_not_count() -> None:
    response = _response([_Part(function_call=_Call("something_else", {"a": 1}))])

    with pytest.raises(LLMOutputError):
        _extract(response, "write_part")


def test_a_rate_limit_is_recognized_as_worth_waiting_for() -> None:
    """Not a bad answer — "not yet". Retrying three times in a second spends
    the whole budget before the window moves, which is how a ten-minute piece
    dies halfway through on a quota that would have cleared."""
    from cadenzra.llm.clients.gemini import _is_rate_limited

    assert _is_rate_limited(Exception("429 RESOURCE_EXHAUSTED. {'error': ...}"))
    assert _is_rate_limited(Exception("503 UNAVAILABLE"))
    assert not _is_rate_limited(Exception("400 INVALID_ARGUMENT"))
    assert not _is_rate_limited(LLMOutputError("the model answered without calling x"))
