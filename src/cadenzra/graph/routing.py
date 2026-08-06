"""Turning what the critic heard into work someone can do.

Validator feedback routes by table lookup — `level` plus the ids name the
target outright. This module exists for the *critic's* feedback, which is the
only genuinely ambiguous input in the system: "section B sounds cluttered"
could be a texture problem, a harmonic-density problem, an interpretation
problem, or a rendering problem (docs/05).

**Cheapest target first.** Anything the router cannot localize confidently goes
to the cheapest plausible layer — interpretation and rendering before harmony
before structure — because misrouting a vague complaint to `plan_structure`
would cascade a full regeneration on the weakest evidence in the system, while
an interpretation change costs one deterministic re-render. This is where the
score/performance split earns most of its keep: "sounds stiff" is a knob, not a
rewrite.
"""

from typing import Final

from cadenzra.model.critique import CritiqueVerdict, Observation
from cadenzra.model.feedback import FeedbackItem, FeedbackLevel
from cadenzra.model.primitives.ids import VoiceId
from cadenzra.model.structure import StructurePlan

SOURCE: Final = "critique_audio"

# Cost order, cheapest first. A re-render costs a subprocess call; a structure
# change costs the entire piece.
LEVEL_COST: Final[dict[FeedbackLevel, int]] = {
    "render": 0,
    "interpretation": 1,
    # Words are cheaper than notes: regenerating a section's lyrics leaves
    # every validated fragment untouched (docs/10).
    "lyric": 2,
    "voice": 3,
    "section": 4,
    "harmony": 5,
    "motif": 6,
    "structure": 7,
}

# Complaints whose natural home is a knob rather than a note. Each phrase names
# something a performer controls, not something the notation says.
_INTERPRETATION_MARKERS: Final[tuple[str, ...]] = (
    "stiff",
    "mechanical",
    "robotic",
    "flat",
    "lifeless",
    "rushed",
    "dragging",
    "no groove",
    "does not groove",
    "doesn't groove",
    "dynamics",
    "crescendo",
    "quiet",
    "loud",
    "swell",
    "expression",
    "unvarying",
)

# Complaints about the sound rather than the performance.
_RENDER_MARKERS: Final[tuple[str, ...]] = (
    "balance",
    "mix",
    "buried",
    "inaudible",
    "timbre",
    "tone quality",
    "distort",
)

# Complaints that genuinely point at the notes.
_VOICE_MARKERS: Final[tuple[str, ...]] = (
    "cluttered",
    "muddy",
    "mud",
    "busy",
    "crowded",
    "clash",
    "dissonan",
    "register",
    "range",
    "line",
)

# Complaints about the piece's shape, which only a new plan can fix.
_STRUCTURE_MARKERS: Final[tuple[str, ...]] = (
    "form",
    "structure",
    "arc",
    "too long",
    "too short",
    "goes nowhere",
    "no direction",
    "repetitive",
)


def route_validator_feedback(item: FeedbackItem) -> FeedbackLevel:
    """Where a validator's feedback goes. A table lookup, by design (docs/05)."""
    return item.level


def classify(observation: Observation) -> FeedbackLevel:
    """The cheapest layer that could plausibly explain an observation.

    Deliberately biased downward. When a phrase matches several layers, the
    cheapest wins, because being wrong about an interpretation parameter costs
    a re-render and being wrong about the structure costs the piece.
    """
    text = observation.concern.lower()
    candidates: list[FeedbackLevel] = []

    if _mentions(text, _RENDER_MARKERS):
        candidates.append("render")
    if _mentions(text, _INTERPRETATION_MARKERS):
        candidates.append("interpretation")
    if _mentions(text, _VOICE_MARKERS):
        candidates.append("voice")
    if _mentions(text, _STRUCTURE_MARKERS):
        candidates.append("structure")

    if not candidates:
        # Unlocalizable. The cheapest thing that could possibly help.
        return "interpretation"
    return min(candidates, key=lambda level: LEVEL_COST[level])


def _mentions(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def localize_verdict(
    verdict: CritiqueVerdict, plan: StructurePlan
) -> list[FeedbackItem]:
    """The critic's observations as routable feedback.

    A rule-based localizer: the vocabulary of complaints about a rendered piece
    is small and stable, and a table over it is inspectable in a way a second
    LLM call is not. The protocol keeps the door open for a model-backed
    router if the phrasing ever outgrows this (docs/08, principle 8).
    """
    known_sections = set(plan.sections_by_id)
    items = []
    for observation in verdict.observations:
        level = classify(observation)
        section_id = (
            observation.section_id
            if observation.section_id in known_sections
            else None
        )
        # Structure-level feedback is about the whole piece, and voice-level
        # feedback needs a voice to act on; without one it is not actionable
        # as a regeneration, so it drops to the cheapest layer instead.
        if level == "voice" and not observation.voice_ids:
            level = "interpretation"

        targets: list[VoiceId | None] = list(observation.voice_ids) or [None]
        for voice_id in targets:
            items.append(
                FeedbackItem(
                    source=SOURCE,
                    level=level,
                    section_id=section_id if level != "structure" else None,
                    voice_id=voice_id,
                    message=observation.concern,
                    evidence=verdict.overall or None,
                )
            )
    return items


def cheapest_level(items: list[FeedbackItem]) -> FeedbackLevel | None:
    """The least expensive layer any of this feedback points at.

    A round of critique addresses one layer at a time, starting with the
    cheapest — there is no sense regenerating a section on the same evidence
    that an expression tweak might resolve.
    """
    if not items:
        return None
    return min((item.level for item in items), key=lambda level: LEVEL_COST[level])
