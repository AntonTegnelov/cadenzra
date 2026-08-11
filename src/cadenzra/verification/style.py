"""`validate_style_pack` — the pack's material must practice what it preaches.

Cells and fragments are exemplars: every voice call builds on them, so a
cell that does not fill its bar, a fragment carrying a structural command,
or a policy that forbids what the idioms demand teaches the same mistake to
the whole piece. `model/style.py` claimed a compile check for years; the
orchestra probe's pack shipped `\\clef` fragments because none existed.
"""

import re
from pathlib import Path
from typing import Final

from cadenzra.common.errors import LilypondCompileError
from cadenzra.interfaces.rendering import ScoreRenderer
from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.primitives.meter import MeterSpec
from cadenzra.model.style import StylePack
from cadenzra.notation.scaffold import scaffold_fragment
from cadenzra.rendering.lilypond import first_error
from cadenzra.verification.voice import FORBIDDEN_COMMANDS, deficit_text

SOURCE: Final = "validate_style"

_COMMAND = re.compile(r"\\(?P<name>[A-Za-z]+)")

# Idiom markers that contradict parallel_fifths_policy="forbid". A declared
# relationship between two fields of one artifact — arithmetic, not taste
# (docs/01 rules out a theory engine; this is not one).
_DOUBLING_WORDS: Final = ("doubl", "parallel", "unison")


def validate_style_pack(
    style: StylePack, renderer: ScoreRenderer, workdir: Path
) -> list[FeedbackItem]:
    """Check one style pack. An empty list means it is accepted."""
    feedback = _check_coherence(style)
    for index, cell in enumerate(style.rhythmic_cells):
        # A cell is exactly one bar of rhythm without its bar check; the
        # check is appended so the compiler can judge "fills the bar".
        feedback += _check_exemplar(
            f"{cell.lily} |",
            cell.meter,
            renderer,
            workdir / f"cell-{index}",
            what=f"the rhythmic cell '{cell.lily}'",
        )
    for index, fragment in enumerate(style.few_shot_fragments):
        feedback += _check_exemplar(
            fragment.lily,
            fragment.meter,
            renderer,
            workdir / f"fragment-{index}",
            what=f"the fragment '{fragment.lily}'",
        )
    return feedback


def _check_coherence(style: StylePack) -> list[FeedbackItem]:
    if style.parallel_fifths_policy != "forbid":
        return []
    for idiom in style.idioms:
        lowered = idiom.lower()
        if "octave" in lowered and any(word in lowered for word in _DOUBLING_WORDS):
            return [
                _item(
                    f"the pack demands '{idiom}' and forbids parallel octaves at "
                    "the same time — every doubled line would be rejected. Set "
                    "parallel_fifths_policy to 'allow' or drop the idiom"
                )
            ]
    return []


def _check_exemplar(
    lily: str,
    meter: MeterSpec,
    renderer: ScoreRenderer,
    workdir: Path,
    *,
    what: str,
) -> list[FeedbackItem]:
    """One exemplar through the same gates a voice fragment faces."""
    forbidden = [
        match["name"]
        for match in _COMMAND.finditer(lily)
        if match["name"] in FORBIDDEN_COMMANDS
    ]
    if forbidden:
        return [
            _item(
                f"{what} uses \\{forbidden[0]}, which belongs to the score "
                "rather than to an exemplar; write only notes, rests, "
                "durations, dynamics and markup"
            )
        ]
    try:
        result = renderer.compile(scaffold_fragment(lily, meter).source, workdir)
    except LilypondCompileError as error:
        return [
            _item(
                f"{what} does not compile: "
                + (first_error(error.output) or "the compiler rejected it"),
                evidence=error.output,
            )
        ]
    return [
        _item(
            f"{what} does not fill a bar of {meter.surface_string()}"
            + _deficit(warning.message, meter)
            + f" — the compiler reports: {warning.message}",
            evidence=warning.message,
        )
        for warning in result.bar_check_warnings
    ]


def _deficit(message: str, meter: MeterSpec) -> str:
    deficit = deficit_text(message, meter)
    return f"; it is {deficit}" if deficit else ""


def _item(message: str, *, evidence: str | None = None) -> FeedbackItem:
    return FeedbackItem(
        source=SOURCE, level="structure", message=message, evidence=evidence
    )
