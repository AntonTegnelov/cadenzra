"""Parsing a `rewrite_bars` reply into replacement bars.

Shape only, as ever (docs/08): whether a replacement bar is good music is the
compiler's and the validators' question, asked after the splice. What is
judged here is the patch's own contract — named bars inside the offered set,
exactly one bar of music each.
"""

from typing import Any

from cadenzra.common.errors import LLMOutputError
from cadenzra.notation.scaffold import count_bar_checks


def parse_bar_patch(
    payload: dict[str, Any], editable_bars: list[int]
) -> dict[int, str]:
    """The replacements by bar number, or `LLMOutputError`."""
    replacements = payload.get("replacements")
    if not isinstance(replacements, list) or not replacements:
        raise LLMOutputError("the patch contains no replacements")

    editable = set(editable_bars)
    parsed: dict[int, str] = {}
    for entry in replacements:
        if not isinstance(entry, dict):
            raise LLMOutputError(f"a replacement is not an object: {entry!r}")
        bar = entry.get("bar")
        music = entry.get("lily_music")
        if not isinstance(bar, int) or not isinstance(music, str) or not music.strip():
            raise LLMOutputError(f"a replacement is missing its bar or music: {entry!r}")
        if bar not in editable:
            raise LLMOutputError(
                f"the patch rewrites bar {bar}, which it was not offered; "
                f"editable bars are {sorted(editable)}"
            )
        music = music.strip()
        # Forgiving, never inventive: append the bar check the contract
        # requires, but refuse music that spans more than its one bar.
        if count_bar_checks(music) == 0:
            music += " |"
        if count_bar_checks(music) != 1:
            raise LLMOutputError(
                f"the replacement for bar {bar} must be exactly one bar "
                f"ending in a single bar check; got: {music!r}"
            )
        parsed[bar] = music
    return parsed
