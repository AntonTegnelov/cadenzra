"""The compiler-stderr parser, against output captured from the real 2.26.

These fixtures are evidence, not assumptions: they were produced by running
LilyPond 2.26.0 on the fixtures in `tests/fixtures/lily/`. A version bump means
regenerating them as an explicit, reviewed step (docs/09).
"""

from pathlib import Path

import pytest

from cadenzra.rendering.lilypond import (
    first_error,
    parse_bar_check_warnings,
    parse_warnings,
)

STDERR = Path(__file__).parent.parent / "fixtures" / "lilypond_stderr"


def _captured(name: str) -> str:
    return (STDERR / f"{name}.txt").read_text(encoding="utf-8")


def test_a_clean_compile_yields_no_warnings() -> None:
    assert parse_bar_check_warnings(_captured("satb_7_8_valid")) == []


def test_an_overfilled_bar_is_located_in_the_source() -> None:
    warnings = parse_bar_check_warnings(_captured("satb_7_8_broken"))

    assert len(warnings) == 1
    warning = warnings[0]
    assert warning.file == "satb_7_8_broken.ly"
    assert warning.line == 17
    assert warning.column == 28
    assert "bar check failed" in warning.message


def test_the_overflow_amount_survives_into_the_message() -> None:
    """The remainder is the evidence a rehearsal note is written from:
    "failed at: 1/8" is one eighth too many."""
    warning = parse_bar_check_warnings(_captured("satb_7_8_broken"))[0]

    assert warning.message.endswith("1/8")


def test_one_bad_bar_produces_one_warning_not_two() -> None:
    """LilyPond interprets the music once per backend, so it reports the same
    failure twice. Two feedback items for one mistake would be noise."""
    captured = _captured("satb_7_8_broken")

    assert captured.count("bar check failed") == 2
    assert len(parse_bar_check_warnings(captured)) == 1


def test_syntax_errors_are_not_bar_check_warnings() -> None:
    """A syntax error exits non-zero and is raised, never routed as a warning."""
    assert parse_bar_check_warnings(_captured("syntax_error")) == []


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("", 0),
        ("Processing `x.ly'\nParsing...\n", 0),
        ("x.ly:3:1: warning: something odd\n", 1),
        ("x.ly:3:1: warning: a\nx.ly:4:1: warning: b\n", 2),
    ],
)
def test_general_warning_parsing_counts(output: str, expected: int) -> None:
    assert len(parse_warnings(output)) == expected


def test_warnings_other_than_bar_checks_are_kept_but_not_misfiled() -> None:
    """Lyric-count mismatches arrive through this same channel (docs/05)."""
    output = (
        "score.ly:70:17: warning: cannot find context: Voice = soprano\n"
        "score.ly:18:26: warning: bar check failed at: 3/8\n"
    )

    assert len(parse_warnings(output)) == 2
    assert len(parse_bar_check_warnings(output)) == 1


def test_the_first_error_carries_the_offending_source_line() -> None:
    """"not a duration" alone sent a live tenor loop through 6/6 identical
    non-compiling attempts — the model was never shown WHICH token was
    broken, so it resubmitted it. The compiler prints the offending source
    on the next line; quoting the compiler means quoting that too."""
    output = (
        "Processing `score.ly'\n"
        "score.ly:62:156: error: not a duration\n"
        "  aes34 g34 f34 ees34 |\n"
        "         ^\n"
    )

    message = first_error(output)

    assert message is not None
    assert "not a duration" in message
    assert "aes34" in message, "the offending source is quoted beside the error"
