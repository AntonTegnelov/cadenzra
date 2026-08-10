"""Parsing a `rewrite_bars` reply into replacement bars.

Shape only, as ever (docs/08): whether a replacement bar is good music is the
compiler's and the validators' question, asked after the splice. What is
judged here is the patch's own contract — named bars inside the offered set,
exactly one bar of music each, and a duration declaration that sums to the
bar.

The declaration is the copy-reflex forcing function: shown its own 15/16
cadence bar and told "1/16 short", a live model returned the same durations
twice, once with a crescendo added. It cannot do that here — the declared
arithmetic is summed exactly, and a copied wrong rhythm fails before anything
compiles. The parser judges the declaration's arithmetic; the compiler stays
the authority on the music itself.
"""

from fractions import Fraction
from typing import Any

from cadenzra.common.errors import LLMOutputError
from cadenzra.llm.parsers.durations import duration_value
from cadenzra.notation.scaffold import count_bar_checks


def parse_bar_patch(
    payload: dict[str, Any], editable_bars: list[int], *, bar_length: Fraction
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
        raw_bar = entry.get("bar")
        music = entry.get("lily_music")
        durations = entry.get("durations")
        if (
            not isinstance(raw_bar, str)
            or not isinstance(music, str)
            or not music.strip()
            or not isinstance(durations, str)
            or not durations.strip()
        ):
            raise LLMOutputError(
                f"a replacement is missing its bar, music or durations: {entry!r}"
            )
        # The schema's enum is strings (Gemini permits enum only on strings);
        # bar numbers are ints everywhere else.
        try:
            bar = int(raw_bar)
        except ValueError:
            raise LLMOutputError(f"a replacement names a non-numeric bar: {raw_bar!r}") from None
        total = sum(
            (duration_value(token) for token in durations.split()), Fraction(0)
        )
        if total != bar_length:
            raise LLMOutputError(
                f"the replacement for bar {bar} declares durations summing to "
                f"{total} of a whole note, but one bar here holds {bar_length} — "
                "recount, then write notes that fill the bar exactly"
            )
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
