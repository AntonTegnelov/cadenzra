"""Node functions: unpack state, delegate, repack.

There is deliberately no logic worth testing here. All intelligence lives below
in `llm/`, `verification/` and `notation/`; all wiring lives beside this in
`build.py`. That is what keeps LangGraph replaceable by editing `graph/` alone
(docs/07).
"""

from dataclasses import dataclass
from pathlib import Path

from cadenzra.app.config import RetryBudgets
from cadenzra.common.errors import BudgetExhaustedError
from cadenzra.interfaces.llm import GeneratorLLM
from cadenzra.interfaces.rendering import ScoreRenderer
from cadenzra.model.contexts import MaterialInstruction, VoiceContext
from cadenzra.model.primitives.ids import SectionId, VoiceId
from cadenzra.model.state import PipelineState, attempt_key, voice_key
from cadenzra.verification.voice import validate_voice


@dataclass(frozen=True)
class Services:
    """The protocol implementations a run is wired with.

    Assembled once in `app/factory.py`, handed to the graph builder. Tests pass
    fakes through the same door, which is why nothing here is ever patched
    (docs/06).
    """

    generator: GeneratorLLM
    renderer: ScoreRenderer
    workdir: Path
    budgets: RetryBudgets


def build_voice_context(
    state: PipelineState, section_id: SectionId, voice_id: VoiceId
) -> VoiceContext:
    """Gather what one voice generation needs from state.

    On a regeneration this carries the rejected fragment and its open feedback,
    so the prompt can ask for a minimal repair rather than a fresh attempt
    (docs/04).
    """
    assert state.structure is not None, "no plan; plan_structure has not run"
    assert state.style is not None, "no style pack; derive_style_pack has not run"

    section = state.structure.sections_by_id[section_id]
    rejected = state.voices.get(voice_key(section_id, voice_id))

    materials = []
    if state.motifs is not None:
        for entry in section.material:
            if entry.voice_id == voice_id and entry.motif_id in state.motifs:
                materials.append(
                    MaterialInstruction(motif=state.motifs[entry.motif_id], entry=entry)
                )

    return VoiceContext(
        section=section,
        voice=state.spec.voices_by_id[voice_id],
        style=state.style,
        skeleton=state.harmony.get(section_id),
        materials=materials,
        rejected=rejected,
        feedback=state.feedback_for("voice", section_id, voice_id),
    )


def generate_voice_node(
    state: PipelineState,
    services: Services,
    section_id: SectionId,
    voice_id: VoiceId,
) -> dict[str, object]:
    """Generate one (section, voice) fragment and clear its stale feedback.

    Superseded feedback is dropped as its target regenerates: only current,
    unresolved issues live in state, and history goes to the run log (docs/05).
    """
    ctx = build_voice_context(state, section_id, voice_id)
    part = services.generator.generate_voice(ctx)

    return {
        "voices": state.voices | {voice_key(section_id, voice_id): part},
        "feedback": [
            item
            for item in state.feedback
            if not (
                item.level == "voice"
                and item.section_id == section_id
                and item.voice_id == voice_id
            )
        ],
    }


def validate_voice_node(
    state: PipelineState,
    services: Services,
    section_id: SectionId,
    voice_id: VoiceId,
) -> dict[str, object]:
    """Validate one fragment and record the attempt against its budget."""
    assert state.structure is not None, "no plan; plan_structure has not run"

    part = state.voice_part(section_id, voice_id)
    feedback = validate_voice(
        part,
        state.spec.voices_by_id[voice_id],
        state.structure.sections_by_id[section_id],
        services.renderer,
        services.workdir / f"{section_id}-{voice_id}",
    )

    key = attempt_key("voice", section_id, voice_id)
    return {
        "feedback": [*state.feedback, *feedback],
        "attempts": state.attempts | {key: state.attempts.get(key, 0) + 1},
    }


def voice_loop_decision(
    state: PipelineState, services: Services, section_id: SectionId, voice_id: VoiceId
) -> str:
    """Whether a validated fragment advances, retries, or exhausts its budget.

    Exhaustion raises rather than returning a verdict: the pipeline never
    completes a run by degrading the music, and a silently padded score is the
    one output this system exists to prevent (docs/02, docs/08 principle 4).
    """
    if not state.feedback_for("voice", section_id, voice_id):
        return "pass"

    key = attempt_key("voice", section_id, voice_id)
    spent = state.attempts.get(key, 0)
    if spent >= services.budgets.voice:
        raise BudgetExhaustedError(
            f"the {voice_id} part for section {section_id} still fails after "
            f"{spent} attempts: "
            + "; ".join(
                item.message for item in state.feedback_for("voice", section_id, voice_id)
            ),
            loop_key=key,
            attempts=spent,
        )
    return "retry"
