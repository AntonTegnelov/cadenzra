"""`validate_structure` — checking the plan before anything is written to it.

The planner proposes; arithmetic disposes (docs/04). Everything here is cheap
and decidable, and catching a bad plan here is the difference between one
regenerated plan and a whole piece written against a wrong map.
"""

from typing import Final

from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.primitives.time import section_length
from cadenzra.model.spec import PieceSpec
from cadenzra.model.structure import GroupRef, SectionPlan, StructurePlan
from cadenzra.verification.transposition import UnknownRelationError, parse_relation

SOURCE: Final = "validate_structure"

# The planner derives bar counts from tempo and meter, so the total should land
# near the requested duration — but "near" is the point: forcing an exact match
# would make the arithmetic dictate the form.
DURATION_TOLERANCE: Final = 0.25


def validate_structure(plan: StructurePlan, spec: PieceSpec) -> list[FeedbackItem]:
    """Check the formal plan. An empty list means it is accepted."""
    return [
        *_check_meters_allowed(plan, spec),
        *_check_voices_resolve(plan, spec),
        *_check_duration(plan, spec),
        *_check_material(plan),
    ]


def _check_meters_allowed(plan: StructurePlan, spec: PieceSpec) -> list[FeedbackItem]:
    """A plan may not exceed the spec's meter palette."""
    allowed = spec.meters_allowed
    feedback = []
    for section in plan.sections:
        if section.meter in allowed:
            continue
        palette = ", ".join(meter.surface_string() for meter in allowed)
        feedback.append(
            _item(
                section.section_id,
                message=(
                    f"section {section.section_id} is in "
                    f"{section.meter.surface_string()}, which is not in this piece's "
                    f"meter palette ({palette})"
                ),
            )
        )
    return feedback


def _check_voices_resolve(plan: StructurePlan, spec: PieceSpec) -> list[FeedbackItem]:
    """Every active voice or group must exist in the spec."""
    known_voices = set(spec.voices_by_id)
    known_groups = spec.groups
    feedback = []
    for section in plan.sections:
        if not section.active_voices:
            feedback.append(
                _item(
                    section.section_id,
                    message=f"section {section.section_id} has no active voices",
                )
            )
        for ref in section.active_voices:
            if isinstance(ref, GroupRef):
                if ref.group not in known_groups:
                    feedback.append(
                        _item(
                            section.section_id,
                            message=(
                                f"section {section.section_id} addresses the group "
                                f"{ref.group!r}, which no voice belongs to"
                            ),
                        )
                    )
            elif ref not in known_voices:
                feedback.append(
                    _item(
                        section.section_id,
                        message=(
                            f"section {section.section_id} names the voice {ref!r}, "
                            f"which is not in this piece ({', '.join(sorted(known_voices))})"
                        ),
                    )
                )
    return feedback


def _check_duration(plan: StructurePlan, spec: PieceSpec) -> list[FeedbackItem]:
    """The bar counts must add up to roughly the requested duration."""
    minutes = sum(_section_minutes(section) for section in plan.sections)
    target = spec.target_minutes
    if abs(minutes - target) <= target * DURATION_TOLERANCE:
        return []
    return [
        _item(
            None,
            message=(
                f"the plan runs about {minutes:.1f} minutes, but the piece was asked "
                f"to be about {target:.1f}; adjust the bar counts "
                f"{'down' if minutes > target else 'up'}"
            ),
        )
    ]


def _section_minutes(section: SectionPlan) -> float:
    """How long a section lasts, from its meter, bar count and tempo.

    A tempo of "quarter = N" means N quarter notes a minute, and a bar is
    `bar_length` whole notes — four quarters each.
    """
    quarters = float(section_length(section.bars, section.meter)) * 4
    return quarters / section.tempo_bpm


def _check_material(plan: StructurePlan) -> list[FeedbackItem]:
    """Declared entries must name declared briefs, with relations we can check.

    A `MaterialEntry` landing inside its own section is already guaranteed by
    `SectionPlan`, so it is not re-checked here — that would be theater
    (docs/08, principle 3).
    """
    briefs = {brief.motif_id for brief in plan.materials_needed}
    feedback = []
    for section in plan.sections:
        active = set(section.voice_ids)
        for entry in section.material:
            if entry.motif_id not in briefs:
                feedback.append(
                    _item(
                        section.section_id,
                        voice_id=entry.voice_id,
                        message=(
                            f"section {section.section_id} places {entry.motif_id!r} at "
                            f"bar {entry.bar}, but no material by that name is planned; "
                            "add it to the materials the piece needs"
                        ),
                    )
                )
            if active and entry.voice_id not in active:
                feedback.append(
                    _item(
                        section.section_id,
                        voice_id=entry.voice_id,
                        message=(
                            f"the entry at bar {entry.bar} of section "
                            f"{section.section_id} is given to {entry.voice_id}, which "
                            "is not singing in that section"
                        ),
                    )
                )
            try:
                parse_relation(entry.relation)
            except UnknownRelationError as error:
                feedback.append(
                    _item(
                        section.section_id,
                        voice_id=entry.voice_id,
                        message=(
                            f"the entry at bar {entry.bar} of section "
                            f"{section.section_id} declares the relation "
                            f"{entry.relation!r}, which cannot be verified; use "
                            "'exact', 'inversion', 'tonal answer', or an interval like "
                            "'P5 up'"
                        ),
                        evidence=str(error),
                    )
                )
    return feedback


def _item(
    section_id: str | None, *, message: str, voice_id: str | None = None,
    evidence: str | None = None,
) -> FeedbackItem:
    return FeedbackItem(
        source=SOURCE,
        level="structure",
        section_id=section_id,
        voice_id=voice_id,
        message=message,
        evidence=evidence,
    )
