"""Wrapping a bare fragment so the compiler can check it.

Per-fragment validation compiles each voice inside a minimal scaffold — the
section's meter, a single staff — so errors are caught while the blast radius
is one voice, before assembly (docs/05).

This module also owns the meter-to-LilyPond mapping, because the scaffolder and
the assembler are the only things that write time signatures and the knowledge
should exist once. Both forms below were confirmed against LilyPond 2.26:
`\\time #'(2 2 3) 7/8` carries beat grouping directly, and `\\timeAbbrev` is
what 2.26 calls the additive meter (`\\compoundMeter` was renamed away).
"""

import re
from typing import Final

from pydantic import BaseModel

from cadenzra.model.primitives.meter import MeterSpec

LILYPOND_VERSION: Final = "2.26.0"
FRAGMENT_VOICE_NAME: Final = "fragment"


def lily_time_command(meter: MeterSpec) -> str:
    """The `\\time` or `\\timeAbbrev` that establishes a meter."""
    if meter.is_additive:
        terms = " ".join(f"({term.numerator} {term.denominator})" for term in meter.terms)
        return f"\\timeAbbrev #'({terms})"
    term = meter.terms[0]
    if meter.grouping is None:
        return f"\\time {term.numerator}/{term.denominator}"
    grouping = " ".join(str(count) for count in meter.grouping)
    return f"\\time #'({grouping}) {term.numerator}/{term.denominator}"


class ScaffoldedSource(BaseModel, frozen=True):
    """A compilable source, plus where the fragment sits inside it.

    `first_fragment_line` lets a compiler warning at source line N be reported
    as a position inside the fragment the generator actually wrote — which is
    the only line number a regeneration prompt can act on.
    """

    source: str
    first_fragment_line: int

    def fragment_line_of(self, source_line: int) -> int:
        """The 1-based line within the fragment for a source line."""
        return source_line - self.first_fragment_line + 1


def scaffold_fragment(
    lily_music: str,
    meter: MeterSpec,
    *,
    clef: str = "treble",
    lily_lyrics: str | None = None,
    midi_instrument: str = "choir aahs",
    tempo_bpm: int = 96,
) -> ScaffoldedSource:
    """Wrap one voice's music expression in the smallest compilable score."""
    header = [
        f'\\version "{LILYPOND_VERSION}"',
        "",
        "\\score {",
        "  <<",
        f'    \\new Staff \\with {{ midiInstrument = "{midi_instrument}" }} {{',
        f'      \\clef {clef}',
        f'      \\new Voice = "{FRAGMENT_VOICE_NAME}" \\absolute {{',
        f"        {lily_time_command(meter)}",
    ]
    fragment_lines = lily_music.strip("\n").split("\n")
    footer = ["      }", "    }"]
    if lily_lyrics is not None:
        # `\lyricsto` takes a music block, so a bare `\lyricmode { ... }` — the
        # form `VoicePart.lily_lyrics` carries — has to be wrapped in braces.
        footer.append(
            f'    \\new Lyrics \\lyricsto "{FRAGMENT_VOICE_NAME}" {{ {lily_lyrics} }}'
        )
    footer += [
        "  >>",
        "  \\layout {}",
        "  \\midi {",
        "    \\context {",
        "      \\Score",
        "      midiChannelMapping = #'staff",
        "    }",
        f"    \\tempo 4 = {tempo_bpm}",
        "  }",
        "}",
        "",
    ]

    return ScaffoldedSource(
        source="\n".join([*header, *fragment_lines, *footer]),
        first_fragment_line=len(header) + 1,
    )


class BarProbe(BaseModel, frozen=True):
    """One tiny score per bar, so every bar's check fires independently.

    A failed bar check desynchronizes the compiler's measure position, so a
    single compile reports only the first of a run of broken bars — a live
    part with twelve identical overfull bars was taught about them one
    attempt at a time. Compiled bar by bar, each check is independent.
    `bar_of_line` maps a warning's source line back to the 1-based bar.
    """

    source: str
    bar_of_line: dict[int, int]


# The first sounding token of a bar, and whether a duration digit rides on
# it. A token scan, not a parser: one letter (note or rest), its accidental
# and octave marks, then optionally digits. The lookbehind keeps letters
# inside command words (\tuplet, \grace, \ff) from matching.
_FIRST_NOTE = re.compile(r"(?<![A-Za-z\\])[a-grs](?:es|is)*[,']*(?P<duration>\d+)?")


def scaffold_bar_probe(lily_music: str, meter: MeterSpec) -> BarProbe | None:
    """The fragment recompiled bar by bar — or None where that is not exact.

    Conservative by design: the probe must reproduce the compiler's own
    arithmetic, so anything that would change meaning in isolation — a
    comment or quoted text surviving the line collapse, a bar whose first
    note inherits its duration from the previous bar (an isolated score
    would default it to a quarter), a final bar missing the check that
    would separate it from its neighbour — returns None, and the caller
    keeps the single compile's report instead.
    """
    if "%" in lily_music or '"' in lily_music:
        return None
    lines = [f'\\version "{LILYPOND_VERSION}"']
    bar_of_line: dict[int, int] = {}
    for number, segment in enumerate(split_bars(lily_music), start=1):
        first_note = _FIRST_NOTE.search(segment)
        if first_note is not None and first_note["duration"] is None:
            return None
        music = " ".join(segment.split())
        if not music.endswith("|"):
            return None
        # The bar-number check is what catches a bar holding an exact
        # multiple of the meter: a | only tests position modulo the bar,
        # so two whole notes in one 4/4 bar pass every check — live, one
        # such bar desynced its voice against the whole assembled score.
        lines.append(
            "\\score { \\new Voice \\absolute { "
            f"{lily_time_command(meter)} {music} \\barNumberCheck #2"
            " } \\layout {} }"
        )
        bar_of_line[len(lines)] = number
    return BarProbe(source="\n".join(lines) + "\n", bar_of_line=bar_of_line)


def bar_of_fragment_line(lily_music: str, line_in_fragment: int) -> int:
    """The bar number a line of a fragment belongs to.

    LilyPond reports warnings at a source line and column, never as a bar
    number, so the bar has to be derived. It is derived by counting the bar
    checks (`|`) that precede the position — which the fragment contract
    requires at every barline (docs/03), and which is a token scan rather than
    a duration parser. That distinction is the whole reason this is allowed to
    touch LilyPond text at all (docs/05).
    """
    lines = lily_music.strip("\n").split("\n")
    preceding = "\n".join(lines[: max(0, line_in_fragment - 1)])
    return _count_bar_checks(preceding) + 1


def bar_of_fragment_position(lily_music: str, line: int, column: int) -> int:
    """As `bar_of_fragment_line`, but exact about position within the line.

    `line` and `column` are 1-based, as LilyPond reports them. A bar check sits
    at the *end* of its bar and the compiler points directly at it, so the
    character at `column` is excluded from the count — a failure reported at a
    barline belongs to the bar that barline closes, not the one after it.
    """
    lines = lily_music.strip("\n").split("\n")
    if not 1 <= line <= len(lines):
        return bar_of_fragment_line(lily_music, line)
    before = "\n".join(lines[: line - 1])
    if before:
        before += "\n"
    before += lines[line - 1][: max(0, column - 1)]
    return _count_bar_checks(before) + 1


def count_bar_checks(text: str) -> int:
    """How many barlines a fragment declares — one per bar, per the contract."""
    return _count_bar_checks(text)


def split_bars(lily_music: str) -> list[str]:
    """The fragment cut at its bar checks, exactly: `"".join` restores it.

    Same token semantics as `count_bar_checks` — quoted `|` ignored, `||`
    one barline — because a second, divergent notion of "bar" is how an
    off-by-one splice is born. Each segment carries its check and trailing
    whitespace; anything after the final check stays with the last bar.
    """
    segments: list[str] = []
    start = 0
    in_string = False
    index = 0
    length = len(lily_music)
    while index < length:
        char = lily_music[index]
        if char == '"':
            in_string = not in_string
            index += 1
        elif char == "|" and not in_string:
            index += 1
            while index < length and lily_music[index] == "|":
                index += 1
            while index < length and lily_music[index] in " \t\n":
                index += 1
            segments.append(lily_music[start:index])
            start = index
        else:
            index += 1
    if start < length:
        if segments:
            segments[-1] += lily_music[start:]
        else:
            segments.append(lily_music[start:])
    return segments


def splice_bars(lily_music: str, replacements: dict[int, str]) -> str:
    """The fragment with the named bars (1-based) replaced, all else verbatim.

    Callers validate the replacement set; a bar number outside the fragment
    here is a broken internal invariant, so it raises rather than clamps.
    """
    bars = split_bars(lily_music)
    for bar in replacements:
        if not 1 <= bar <= len(bars):
            raise ValueError(
                f"cannot replace bar {bar}: the fragment has {len(bars)} bars"
            )
    spliced = []
    for number, segment in enumerate(bars, start=1):
        if number in replacements:
            tail = segment[len(segment.rstrip()) :] or "\n"
            spliced.append(replacements[number].strip() + tail)
        else:
            spliced.append(segment)
    return "".join(spliced)


def _count_bar_checks(text: str) -> int:
    """Bar checks in `text`, ignoring the `|` inside other constructs.

    LilyPond writes repeat barlines as `\\bar "|:"` — inside a string — and
    `||` in the same way, so counting only bare `|` tokens outside quotes is
    enough. Nothing here interprets durations.
    """
    count = 0
    in_string = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == '"':
            in_string = not in_string
        elif char == "|" and not in_string:
            # `|` doubled (`||`) is one barline, not two.
            count += 1
            while index + 1 < len(text) and text[index + 1] == "|":
                index += 1
        index += 1
    return count
