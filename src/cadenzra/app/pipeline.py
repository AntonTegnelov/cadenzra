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
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import mido

from cadenzra.app.config import RetryBudgets
from cadenzra.common.errors import (
    BudgetExhaustedError,
    LilypondCompileError,
    LLMOutputError,
)
from cadenzra.common.runlog import RunLog
from cadenzra.interfaces.llm import GeneratorLLM
from cadenzra.interfaces.rendering import ScoreRenderer
from cadenzra.model.contexts import HarmonyContext, MotifContext
from cadenzra.model.feedback import FeedbackItem, FeedbackLevel
from cadenzra.model.harmony import HarmonicSkeleton
from cadenzra.model.lyrics import LyricPlan
from cadenzra.model.motif import Motif, MotifLibrary
from cadenzra.model.primitives.ids import MotifId, SectionId
from cadenzra.model.primitives.meter import MeterSpec
from cadenzra.model.primitives.time import bar_containing
from cadenzra.model.state import PipelineState, attempt_key
from cadenzra.model.structure import SectionPlan, StructurePlan
from cadenzra.model.style import StylePack
from cadenzra.notation.scaffold import scaffold_fragment
from cadenzra.verification.harmony import (
    check_entries_against_grid,
    pinned_entry_tones,
    validate_harmony,
)
from cadenzra.verification.lyrics import validate_lyric_plan
from cadenzra.verification.midi_analysis import NoteEvent, extract_voice_notes
from cadenzra.verification.motifs import validate_motifs
from cadenzra.verification.structure import validate_structure
from cadenzra.verification.style import validate_style_pack

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LayerServices:
    """What the structured layers are wired with."""

    generator: GeneratorLLM
    renderer: ScoreRenderer
    workdir: Path
    budgets: RetryBudgets
    # Keyword-only so subclasses may still declare required fields after it.
    runlog: RunLog | None = field(default=None, kw_only=True)


def derive_style(state: PipelineState, services: LayerServices) -> PipelineState:
    """Interpret the style brief exactly once, for the whole run (docs/04).

    Once, but not necessarily on the first try. This was the one layer with no
    retry, and a single mistyped meter in a single rhythmic cell — "3/3" where
    the piece allows 3/4 — ended a twelve-voice run before it had written a
    note. The parser's complaint is a perfectly good instruction to the next
    attempt.

    A present slice is not regenerated: that is what lets a resumed run skip
    the layers a previous run already paid for (the same shape in every layer
    below).
    """
    if state.style is not None:
        _log.info("style pack already present; skipping")
        return state
    _log.info("deriving the style pack")

    def generate(feedback: list[FeedbackItem]) -> StylePack:
        return services.generator.derive_style_pack(state.spec, feedback)

    style = _converge(
        generate,
        lambda candidate: validate_style_pack(
            candidate, services.renderer, services.workdir / "style"
        ),
        budget=services.budgets.structure,
        loop_key=attempt_key("structure", None, None),
        what="the style pack",
        runlog=services.runlog,
    )
    return state.model_copy(
        update={"style": style, "interpretation": style.interpretation_defaults}
    )


def plan_structure(state: PipelineState, services: LayerServices) -> PipelineState:
    """Plan the form, then check it with arithmetic (docs/04)."""
    style = _require_style(state)
    if state.structure is not None:
        _log.info("form already planned; skipping")
        return state
    _log.info("planning the form")

    def generate(feedback: list[FeedbackItem]) -> StructurePlan:
        return services.generator.plan_structure(state.spec, style, feedback)

    plan = _converge(
        generate,
        lambda candidate: validate_structure(candidate, state.spec),
        budget=services.budgets.structure,
        loop_key=attempt_key("structure", None, None),
        what="the plan",
        runlog=services.runlog,
    )
    return state.model_copy(update={"structure": plan})


def plan_lyrics(state: PipelineState, services: LayerServices) -> PipelineState:
    """Decide what the words say, before any of them are written (docs/10).

    Skipped entirely for instrumental pieces — the same conditional-skip shape
    the motif layer uses, and the reason an instrumental spec never sees a word
    of the device vocabulary.
    """
    style, plan = _require_style(state), _require_plan(state)
    if not state.spec.has_lyrics or state.lyric_plan is not None:
        return state

    _log.info("planning the words")

    def generate(feedback: list[FeedbackItem]) -> LyricPlan:
        return services.generator.plan_lyrics(state.spec, style, plan, feedback)

    lyric_plan = _converge(
        generate,
        lambda candidate: validate_lyric_plan(candidate, plan, state.spec),
        budget=services.budgets.lyric_plan,
        loop_key=attempt_key("lyric_plan", None, None),
        what="the lyric plan",
        runlog=services.runlog,
    )
    return state.model_copy(update={"lyric_plan": lyric_plan})


def generate_motifs(state: PipelineState, services: LayerServices) -> PipelineState:
    """Write the recurring material — skipped when the form declares none.

    This is the conditional skip from docs/02: a through-composed piece never
    calls the motif layer at all.
    """
    style, plan = _require_style(state), _require_plan(state)
    if not plan.declares_materials:
        _log.info("no material declared; skipping the motif layer")
        return state
    if state.motifs is not None:
        _log.info("motifs already written; skipping")
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
            library,
            plan,
            state.spec,
            services.renderer,
            services.workdir / "motifs",
            parallel_policy=style.parallel_fifths_policy,
        )

    motifs = _converge(
        generate,
        validate,
        budget=services.budgets.motifs,
        loop_key=attempt_key("motif", None, None),
        what="the motifs",
        runlog=services.runlog,
    )
    return state.model_copy(update={"motifs": motifs})


def generate_harmony(state: PipelineState, services: LayerServices) -> PipelineState:
    """One skeleton per section, in performance order.

    Sequential — unlike voice generation — because harmonic continuity across
    section boundaries is the point, and the previous section's tail is the
    sliding-window context (docs/04).
    """
    style, plan = _require_style(state), _require_plan(state)
    if state.harmony:
        _log.info("harmony already written; skipping")
        return state

    skeletons: dict[SectionId, HarmonicSkeleton] = {}
    previous_section: SectionPlan | None = None
    previous_skeleton: HarmonicSkeleton | None = None
    # Compiled once for the whole layer: the grid is checked against the
    # subjects it will have to harmonize, at the layer that can still move.
    motif_notes = analyzed_motifs(state, services.renderer, services.workdir)

    for section in plan.sections:
        _log.info("writing harmony for section %s", section.section_id)
        skeleton = _harmony_for(
            state,
            services,
            section,
            style,
            previous_section=previous_section,
            previous_skeleton=previous_skeleton,
            motif_notes=motif_notes,
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
    motif_notes: dict[MotifId, list[NoteEvent]] | None = None,
    prior: list[FeedbackItem] | None = None,
) -> HarmonicSkeleton:
    """One section's skeleton, to convergence.

    Its own function so the loop variables are bound as arguments rather than
    captured — a closure over a loop variable is exactly the bug this shape
    prevents.
    """
    motifs = _motifs_in(state, section)

    pinned = pinned_entry_tones(section, motif_notes or {})

    def generate(feedback: list[FeedbackItem]) -> HarmonicSkeleton:
        return services.generator.generate_harmony(
            HarmonyContext(
                section=section,
                style=style,
                motifs=motifs,
                pinned=pinned,
                previous_section=previous_section,
                previous_skeleton=previous_skeleton,
                feedback=feedback,
            )
        )

    def validate(candidate: HarmonicSkeleton) -> list[FeedbackItem]:
        return [
            *validate_harmony(candidate, section),
            *check_entries_against_grid(
                candidate, section, motif_notes or {}, style.dissonance_policy
            ),
        ]

    return _converge(
        generate,
        validate,
        budget=services.budgets.harmony,
        loop_key=attempt_key("harmony", section.section_id, None),
        what=f"the harmony for section {section.section_id}",
        runlog=services.runlog,
        prior=prior,
    )


def regenerate_section_harmony(
    state: PipelineState,
    services: LayerServices,
    section_id: SectionId,
    prior: list[FeedbackItem],
) -> PipelineState:
    """One section's grid, regenerated against evidence no voice can fix.

    The runtime loop-back for plan-level contradictions the plan-time check
    cannot predict (a tonal answer's realization is not known until written):
    the fix returns to the layer that owns the mistake, with the violation
    quoted (CLAUDE.md). The regenerated grid passes back through the same
    validators — including the entries check — before it is accepted.
    """
    plan = state.structure
    assert plan is not None and state.style is not None
    sections = plan.sections
    index = next(
        i for i, section in enumerate(sections) if section.section_id == section_id
    )
    previous_section = sections[index - 1] if index else None
    previous_skeleton = (
        state.harmony.get(previous_section.section_id)
        if previous_section is not None
        else None
    )
    skeleton = _harmony_for(
        state,
        services,
        sections[index],
        state.style,
        previous_section=previous_section,
        previous_skeleton=previous_skeleton,
        motif_notes=analyzed_motifs(state, services.renderer, services.workdir),
        prior=prior,
    )
    return state.model_copy(
        update={"harmony": {**state.harmony, section_id: skeleton}}
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


def analyzed_motifs(
    state: PipelineState, renderer: ScoreRenderer, workdir: Path
) -> dict[MotifId, list[NoteEvent]]:
    """Each motif compiled and analyzed, so declared entries can be verified.

    This is what turns "themes that return" from a claim into a checked
    property: `validate_section` compares the realized music at each declared
    position against these notes under the declared relation (docs/03). It
    lives here rather than in `compose` so the harmony loop can consult the
    same notes when it checks the grid against declared entries.
    """
    if state.motifs is None or state.structure is None:
        return {}

    analyzed: dict[MotifId, list[NoteEvent]] = {}
    for motif_id, motif in state.motifs.motifs.items():
        meter = _motif_meter(state, motif_id)
        scaffolded = scaffold_fragment(motif.lily_music, meter)
        try:
            result = renderer.compile(scaffolded.source, workdir / f"motif-{motif_id}")
        except LilypondCompileError:
            continue
        if result.midi_path is None:
            continue
        for notes in extract_voice_notes(mido.MidiFile(result.midi_path)).values():
            analyzed[motif_id] = notes
            break
    return analyzed


def _motif_meter(state: PipelineState, motif_id: MotifId) -> MeterSpec:
    """The meter a motif is written in — the first section that declares it."""
    assert state.structure is not None
    for section in state.structure.sections:
        if any(entry.motif_id == motif_id for entry in section.material):
            return section.meter
    return state.spec.meters_allowed[0]


def feedback_dicts(
    feedback: list[FeedbackItem],
    meters: Mapping[SectionId, MeterSpec] | None = None,
) -> list[dict[str, Any]]:
    """Feedback as the plain dicts the run log records beside the messages.

    The run log imports nothing from cadenzra, so the conversion happens here.
    `bar` needs the section's meter; callers without one (the structured
    layers) simply record it as absent.
    """
    dicts: list[dict[str, Any]] = []
    for item in feedback:
        meter = (meters or {}).get(item.section_id) if item.section_id else None
        bar = (
            bar_containing(item.location, meter)
            if item.location is not None and meter is not None
            else None
        )
        dicts.append(
            {
                "id": item.fingerprint(),
                "kind": item.kind or item.source,
                "section": item.section_id,
                "voices": list(item.voices),
                "voice": item.voice_id,
                "bar": bar,
                "message": item.message,
                "routing": item.routing,
            }
        )
    return dicts


def _converge[T](
    generate: Callable[[list[FeedbackItem]], T],
    validate: Callable[[T], list[FeedbackItem]],
    *,
    budget: int,
    loop_key: str,
    what: str,
    runlog: RunLog | None = None,
    prior: list[FeedbackItem] | None = None,
) -> T:
    """Generate and validate until clean, or fail loudly when the budget runs out.

    A validator re-runs *in full* after every regeneration: there is no "fixed
    the reported issue, skip the rest" path, because a regeneration can
    introduce new errors anywhere in the artifact (docs/05).

    `prior` seeds the first prompt with feedback from a later layer — the
    regrid loop-back hands the assembly's evidence to the harmony layer here.
    """
    feedback: list[FeedbackItem] = list(prior or [])
    for attempt in range(1, budget + 1):
        try:
            candidate = generate(feedback)
        except LLMOutputError as error:
            # An artifact that will not parse is a rejection like any other,
            # and the parser's complaint is the diagnosis — quoted, not
            # paraphrased. Letting it escape would end the run over something
            # the next attempt could fix if it were only told.
            feedback = [
                FeedbackItem(source="parser", level=_level_of(loop_key), message=str(error))
            ]
            _log.warning(
                "%s came back malformed on attempt %d/%d: %s",
                what,
                attempt,
                budget,
                error,
            )
            if runlog is not None:
                runlog.validation(
                    what=what,
                    loop_key=loop_key,
                    attempt=attempt,
                    budget=budget,
                    messages=[str(error)],
                    items=feedback_dicts(feedback),
                )
            continue

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
        if runlog is not None:
            runlog.validation(
                what=what,
                loop_key=loop_key,
                attempt=attempt,
                budget=budget,
                messages=[item.message for item in feedback],
                items=feedback_dicts(feedback),
            )

    raise BudgetExhaustedError(
        f"{what} still fails after {budget} attempts: "
        + "; ".join(item.message for item in feedback),
        loop_key=loop_key,
        attempts=budget,
    )


def _level_of(loop_key: str) -> FeedbackLevel:
    """The feedback level a loop key belongs to (`attempt_key` builds them)."""
    level = loop_key.split(":", 1)[0]
    return cast(FeedbackLevel, "lyric" if level == "lyric_plan" else level)


def _require_style(state: PipelineState) -> StylePack:
    """A missing style pack here is a broken invariant, not a case to handle."""
    assert state.style is not None, "derive_style has not run"
    return state.style


def _require_plan(state: PipelineState) -> StructurePlan:
    assert state.structure is not None, "plan_structure has not run"
    return state.structure
