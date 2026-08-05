"""The composition pipeline as an explicit sequence of layers.

Each layer generates, validates, and loops back on failure within its own
budget; a failure that outlasts the budget ends the run loudly, with everything
produced so far written out (docs/02).

This drives the structured layers directly rather than through LangGraph. That
is a deliberate, stated choice: the design buys LangGraph for *conditional
feedback edges*, and these loops are all one shape — generate, validate, retry
the same node — which a plain loop expresses more clearly than a graph does.
The graph earns its keep at the (section x voice) fan-out and the feedback
router, which is where it is used (docs/08, principle 1). Nodes stay plain
functions over state either way.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cadenzra.app.config import RetryBudgets
from cadenzra.common.errors import BudgetExhaustedError
from cadenzra.interfaces.llm import GeneratorLLM
from cadenzra.interfaces.rendering import ScoreRenderer
from cadenzra.model.contexts import HarmonyContext, MotifContext
from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.harmony import HarmonicSkeleton
from cadenzra.model.motif import Motif, MotifLibrary
from cadenzra.model.primitives.ids import SectionId
from cadenzra.model.state import PipelineState, attempt_key
from cadenzra.model.structure import SectionPlan, StructurePlan
from cadenzra.model.style import StylePack
from cadenzra.verification.harmony import validate_harmony
from cadenzra.verification.motifs import validate_motifs
from cadenzra.verification.structure import validate_structure

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LayerServices:
    """What the structured layers are wired with."""

    generator: GeneratorLLM
    renderer: ScoreRenderer
    workdir: Path
    budgets: RetryBudgets


def derive_style(state: PipelineState, services: LayerServices) -> PipelineState:
    """Interpret the style brief exactly once, for the whole run (docs/04)."""
    _log.info("deriving the style pack")
    style: StylePack = services.generator.derive_style_pack(state.spec)
    return state.model_copy(
        update={"style": style, "interpretation": style.interpretation_defaults}
    )


def plan_structure(state: PipelineState, services: LayerServices) -> PipelineState:
    """Plan the form, then check it with arithmetic (docs/04)."""
    style = _require_style(state)
    _log.info("planning the form")

    def generate(feedback: list[FeedbackItem]) -> StructurePlan:
        return services.generator.plan_structure(state.spec, style, feedback)

    plan = _converge(
        generate,
        lambda candidate: validate_structure(candidate, state.spec),
        budget=services.budgets.structure,
        loop_key=attempt_key("structure", None, None),
        what="the plan",
    )
    return state.model_copy(update={"structure": plan})


def generate_motifs(state: PipelineState, services: LayerServices) -> PipelineState:
    """Write the recurring material — skipped when the form declares none.

    This is the conditional skip from docs/02: a through-composed piece never
    calls the motif layer at all.
    """
    style, plan = _require_style(state), _require_plan(state)
    if not plan.declares_materials:
        _log.info("no material declared; skipping the motif layer")
        return state

    _log.info("writing %d motifs", len(plan.materials_needed))

    def generate(feedback: list[FeedbackItem]) -> MotifLibrary:
        return services.generator.generate_motifs(
            MotifContext(
                briefs=plan.materials_needed,
                spec=state.spec,
                style=style,
                plan=plan,
                feedback=feedback,
            )
        )

    def validate(library: MotifLibrary) -> list[FeedbackItem]:
        return validate_motifs(
            library, plan, state.spec, services.renderer, services.workdir / "motifs"
        )

    motifs = _converge(
        generate,
        validate,
        budget=services.budgets.motifs,
        loop_key=attempt_key("motif", None, None),
        what="the motifs",
    )
    return state.model_copy(update={"motifs": motifs})


def generate_harmony(state: PipelineState, services: LayerServices) -> PipelineState:
    """One skeleton per section, in performance order.

    Sequential — unlike voice generation — because harmonic continuity across
    section boundaries is the point, and the previous section's tail is the
    sliding-window context (docs/04).
    """
    style, plan = _require_style(state), _require_plan(state)

    skeletons: dict[SectionId, HarmonicSkeleton] = {}
    previous_section: SectionPlan | None = None
    previous_skeleton: HarmonicSkeleton | None = None

    for section in plan.sections:
        _log.info("writing harmony for section %s", section.section_id)
        skeleton = _harmony_for(
            state,
            services,
            section,
            style,
            previous_section=previous_section,
            previous_skeleton=previous_skeleton,
        )
        skeletons[section.section_id] = skeleton
        previous_section, previous_skeleton = section, skeleton

    return state.model_copy(update={"harmony": skeletons})


def _harmony_for(
    state: PipelineState,
    services: LayerServices,
    section: SectionPlan,
    style: StylePack,
    *,
    previous_section: SectionPlan | None,
    previous_skeleton: HarmonicSkeleton | None,
) -> HarmonicSkeleton:
    """One section's skeleton, to convergence.

    Its own function so the loop variables are bound as arguments rather than
    captured — a closure over a loop variable is exactly the bug this shape
    prevents.
    """
    motifs = _motifs_in(state, section)

    def generate(feedback: list[FeedbackItem]) -> HarmonicSkeleton:
        return services.generator.generate_harmony(
            HarmonyContext(
                section=section,
                style=style,
                motifs=motifs,
                previous_section=previous_section,
                previous_skeleton=previous_skeleton,
                feedback=feedback,
            )
        )

    return _converge(
        generate,
        lambda candidate: validate_harmony(candidate, section),
        budget=services.budgets.harmony,
        loop_key=attempt_key("harmony", section.section_id, None),
        what=f"the harmony for section {section.section_id}",
    )


def _motifs_in(state: PipelineState, section: SectionPlan) -> list[Motif]:
    """The motifs this section carries, so the harmony accommodates them."""
    if state.motifs is None:
        return []
    return [
        state.motifs[entry.motif_id]
        for entry in section.material
        if entry.motif_id in state.motifs
    ]


def _converge[T](
    generate: Callable[[list[FeedbackItem]], T],
    validate: Callable[[T], list[FeedbackItem]],
    *,
    budget: int,
    loop_key: str,
    what: str,
) -> T:
    """Generate and validate until clean, or fail loudly when the budget runs out.

    A validator re-runs *in full* after every regeneration: there is no "fixed
    the reported issue, skip the rest" path, because a regeneration can
    introduce new errors anywhere in the artifact (docs/05).
    """
    feedback: list[FeedbackItem] = []
    for attempt in range(1, budget + 1):
        candidate = generate(feedback)
        feedback = validate(candidate)
        if not feedback:
            return candidate
        _log.warning(
            "%s failed validation on attempt %d/%d: %s",
            what,
            attempt,
            budget,
            "; ".join(item.message for item in feedback),
        )

    raise BudgetExhaustedError(
        f"{what} still fails after {budget} attempts: "
        + "; ".join(item.message for item in feedback),
        loop_key=loop_key,
        attempts=budget,
    )


def _require_style(state: PipelineState) -> StylePack:
    """A missing style pack here is a broken invariant, not a case to handle."""
    assert state.style is not None, "derive_style has not run"
    return state.style


def _require_plan(state: PipelineState) -> StructurePlan:
    assert state.structure is not None, "plan_structure has not run"
    return state.structure
