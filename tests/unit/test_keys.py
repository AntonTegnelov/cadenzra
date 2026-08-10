"""Key strings decide the spelling of the feedback surface."""

import pytest

from cadenzra.notation.keys import parse_key, prefer_flats


@pytest.mark.parametrize(
    ("key", "flats"),
    [
        ("c major", False),
        ("c minor", True),  # relative Eb
        ("d minor", True),  # relative F
        ("e minor", False),  # relative G
        ("d phrygian", True),  # the Bb-major collection
        ("f lydian", False),  # the C-major collection
        ("g mixolydian", False),
        ("bb major", True),
        ("fis minor", False),
    ],
)
def test_the_relative_major_decides_the_spelling(key: str, flats: bool) -> None:
    assert prefer_flats(key) is flats


def test_an_unreadable_key_stays_on_the_sharp_default() -> None:
    assert prefer_flats("") is False
    assert prefer_flats("h wobbly") is False


def test_parse_key_reads_tonic_and_mode() -> None:
    parsed = parse_key("d phrygian")

    assert parsed is not None
    tonic, mode = parsed
    assert tonic.step == "D" and mode == "phrygian"


def test_a_bare_tonic_defaults_to_major() -> None:
    parsed = parse_key("g")

    assert parsed is not None
    assert parsed[1] == "major"
