"""The whole run: spec in, five consistent artifacts out.

The dependency direction is absolute (docs/03): LilyPond source -> score
artifacts -> performance artifacts. Nothing is edited downstream of its source;
a fix loops back to the layer that owns the mistake and everything after it is
rebuilt.

When a retry budget runs out, the run ends non-zero with everything produced so
far written to the output directory, including the failing fragment and its
feedback. It never pads, truncates, or auto-fixes music to force completion — a
silently corrupted score is the one output this system exists to prevent
(docs/02, docs/08 principle 4).
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import mido

from cadenzra.app.config import RunConfig
from cadenzra.app.pipeline import (
    LayerServices,
    derive_style,
    generate_harmony,
    generate_motifs,
    plan_structure,
)
from cadenzra.common.errors import (
    BudgetExhaustedError,
    CadenzraError,
    LilypondCompileError,
)
from cadenzra.interfaces.rendering import Synthesizer
from cadenzra.model.artifacts import AssembledSection, RenderedArtifacts
from cadenzra.model.contexts import MaterialInstruction, VoiceContext
from cadenzra.model.feedback import FeedbackItem
from cadenzra.model.interpretation import InterpretationParams
from cadenzra.model.primitives.ids import MotifId, SectionId, VoiceId
from cadenzra.model.primitives.meter import MeterSpec
from cadenzra.model.spec import PieceSpec
from cadenzra.model.state import PipelineState, attempt_key, voice_key
from cadenzra.model.structure import GroupRef, SectionPlan
from cadenzra.model.voice import VoicePart
from cadenzra.notation.assemble import assemble_score, assemble_section
from cadenzra.notation.scaffold import scaffold_fragment
from cadenzra.performance.interpret import interpret_performance
from cadenzra.verification.midi_analysis import (
    NoteEvent,
    channel_track_invariant_ok,
    extract_voice_notes,
)
from cadenzra.verification.section import validate_section
from cadenzra.verification.voice import validate_voice

_log = logging.getLogger(__name__)

# The last few bars of a voice's previous section, shown so lines connect
# across boundaries (docs/04).
_SLIDING_WINDOW_BARS = 3


@dataclass(frozen=True)
class ComposeServices(LayerServices):
    """The layer services plus what only a full run needs."""

    synthesizer: Synthesizer
    output_dir: Path


def compose(spec: PieceSpec, services: ComposeServices) -> PipelineState:
    """Run the whole pipeline. Raises `CadenzraError` on an exhausted budget."""
    state = PipelineState(spec=spec)
    try:
        state = derive_style(state, services)
        state = plan_structure(state, services)
        state = generate_motifs(state, services)
        state = generate_harmony(state, services)
        state = generate_voices(state, services)
        state = assemble_and_verify(state, services)
        state = render(state, services)
    except CadenzraError:
        _write_partials(state, services.output_dir)
        raise
    _write_partials(state, services.output_dir)
    return state


def generate_voices(state: PipelineState, services: ComposeServices) -> PipelineState:
    """Every (section, voice) pair, section by section.

    Within a section voices are independent given the skeleton, so they run
    concurrently. Across sections generation is sequential per voice, because
    the sliding window needs the previous section to exist (docs/04).
    """
    plan = state.structure
    assert plan is not None

    for section in plan.sections:
        voice_ids = _voices_in(section, state.spec)
        _log.info(
            "writing %d voices for section %s", len(voice_ids), section.section_id
        )
        results = _write_section_voices(state, services, section, voice_ids)
        state = state.model_copy(
            update={
                "voices": state.voices
                | {
                    voice_key(section.section_id, part.voice_id): part
                    for part in results
                },
                "attempts": state.attempts
                | {
                    attempt_key("voice", section.section_id, part.voice_id): 1
                    for part in results
                },
            }
        )
    return state


def _write_section_voices(
    state: PipelineState,
    services: ComposeServices,
    section: SectionPlan,
    voice_ids: list[VoiceId],
) -> list[VoicePart]:
    """One section's voices, written concurrently.

    Its own function so `state` and `section` are bound as arguments rather
    than captured by a closure over a loop variable.
    """
    with ThreadPoolExecutor(max_workers=max(1, len(voice_ids))) as pool:
        return list(
            pool.map(
                lambda voice_id: _voice_to_convergence(
                    state, services, section, voice_id
                ),
                voice_ids,
            )
        )


def _voices_in(section: SectionPlan, spec: PieceSpec) -> list[VoiceId]:
    """Which voices sing here, resolving any group references."""
    named = set(section.voice_ids)
    for ref in section.active_voices:
        if isinstance(ref, GroupRef):
            named |= {v.voice_id for v in spec.voices if v.group == ref.group}
    if not named:
        named = set(spec.voices_by_id)
    return [voice.voice_id for voice in spec.voices if voice.voice_id in named]


def _voice_to_convergence(
    state: PipelineState,
    services: ComposeServices,
    section: SectionPlan,
    voice_id: VoiceId,
    *,
    prior: list[FeedbackItem] | None = None,
) -> VoicePart:
    """One fragment, regenerated against its feedback until it validates.

    `prior` seeds the first attempt with feedback from a *later* layer — the
    cross-voice checks — which the fragment on its own would always pass.
    """
    voice_spec = state.spec.voices_by_id[voice_id]
    feedback: list[FeedbackItem] = list(prior or [])
    rejected: VoicePart | None = (
        state.voices.get(voice_key(section.section_id, voice_id)) if prior else None
    )

    for attempt in range(1, services.budgets.voice + 1):
        ctx = VoiceContext(
            section=section,
            voice=voice_spec,
            style=state.style,  # type: ignore[arg-type]
            skeleton=state.harmony.get(section.section_id),
            materials=_materials_for(state, section, voice_id),
            previous_tail=_previous_tail(state, section, voice_id),
            rejected=rejected,
            feedback=feedback,
        )
        part = services.generator.generate_voice(ctx)
        feedback = validate_voice(
            part,
            voice_spec,
            section,
            services.renderer,
            services.workdir / f"{section.section_id}-{voice_id}-{attempt}",
        )
        if not feedback:
            return part
        rejected = part
        _log.warning(
            "%s in section %s failed on attempt %d/%d: %s",
            voice_id,
            section.section_id,
            attempt,
            services.budgets.voice,
            "; ".join(item.message for item in feedback),
        )

    raise BudgetExhaustedError(
        f"the {voice_id} part for section {section.section_id} still fails after "
        f"{services.budgets.voice} attempts: "
        + "; ".join(item.message for item in feedback),
        loop_key=attempt_key("voice", section.section_id, voice_id),
        attempts=services.budgets.voice,
    )


def _materials_for(
    state: PipelineState, section: SectionPlan, voice_id: VoiceId
) -> list[MaterialInstruction]:
    if state.motifs is None:
        return []
    return [
        MaterialInstruction(motif=state.motifs[entry.motif_id], entry=entry)
        for entry in section.material
        if entry.voice_id == voice_id and entry.motif_id in state.motifs
    ]


def _previous_tail(
    state: PipelineState, section: SectionPlan, voice_id: VoiceId
) -> str | None:
    """The last few bars this voice sang, so its line connects across the seam."""
    plan = state.structure
    assert plan is not None
    order = [item.section_id for item in plan.sections]
    index = order.index(section.section_id)
    for previous in reversed(order[:index]):
        part = state.voices.get(voice_key(previous, voice_id))
        if part is not None:
            bars = part.lily_music.split("|")
            return "|".join(bars[-(_SLIDING_WINDOW_BARS + 1) :]).strip()
    return None


def assemble(state: PipelineState, services: ComposeServices) -> PipelineState:
    """Wrap validated fragments in structure, then check them together."""
    del services
    plan = state.structure
    assert plan is not None and state.style is not None

    sections: dict[SectionId, AssembledSection] = {}
    for section in plan.sections:
        parts = {
            voice_id: state.voice_part(section.section_id, voice_id)
            for voice_id in _voices_in(section, state.spec)
        }
        sections[section.section_id] = assemble_section(section, parts, state.spec)

    score = assemble_score(plan, sections, state.spec)
    return state.model_copy(update={"sections": sections, "score": score})


def assemble_and_verify(
    state: PipelineState, services: ComposeServices
) -> PipelineState:
    """Assemble, run the cross-voice checks, and loop back on failure.

    This is the feedback edge docs/02 draws from `validate_section` back to
    `generate_voice`: a cross-voice problem is not a property of any one
    fragment, so it can only be found here — and the fix belongs to the
    *specific voices* the feedback names, not to the section as a whole.
    Regenerating only those keeps the blast radius small, which is the whole
    reason validation is scoped this way.
    """
    for attempt in range(1, services.budgets.section + 1):
        state = assemble(state, services)
        feedback = _verify_assembled(state, services)
        if not feedback:
            return state

        targets = _targets_of(feedback)
        _log.warning(
            "cross-voice checks failed on attempt %d/%d: %s",
            attempt,
            services.budgets.section,
            "; ".join(item.message for item in feedback),
        )
        if not targets:
            break
        state = _rewrite_voices(state, services, feedback, targets)

    raise BudgetExhaustedError(
        "the assembled score still fails cross-voice checks after "
        f"{services.budgets.section} attempts: "
        + "; ".join(item.message for item in feedback),
        loop_key=attempt_key("section", None, None),
        attempts=services.budgets.section,
    )


def _targets_of(
    feedback: list[FeedbackItem],
) -> dict[tuple[SectionId, VoiceId], list[FeedbackItem]]:
    """Group feedback by the (section, voice) that must regenerate.

    Feedback naming no voice cannot be routed to one, so it is left out rather
    than assigned to an arbitrary part.
    """
    targets: dict[tuple[SectionId, VoiceId], list[FeedbackItem]] = {}
    for item in feedback:
        if item.section_id is None or item.voice_id is None:
            continue
        targets.setdefault((item.section_id, item.voice_id), []).append(item)
    return targets


def _rewrite_voices(
    state: PipelineState,
    services: ComposeServices,
    feedback: list[FeedbackItem],
    targets: dict[tuple[SectionId, VoiceId], list[FeedbackItem]],
) -> PipelineState:
    """Regenerate exactly the parts the cross-voice feedback named."""
    plan = state.structure
    assert plan is not None
    sections = plan.sections_by_id

    rewritten = {}
    for (section_id, voice_id), items in targets.items():
        _log.info("rewriting %s in section %s", voice_id, section_id)
        part = _voice_to_convergence(
            state.model_copy(update={"feedback": feedback}),
            services,
            sections[section_id],
            voice_id,
            prior=items,
        )
        rewritten[voice_key(section_id, voice_id)] = part

    return state.model_copy(update={"voices": state.voices | rewritten})


def _verify_assembled(
    state: PipelineState, services: ComposeServices
) -> list[FeedbackItem]:
    """Compile the assembled score and run the cross-voice checks on it."""
    score = state.score
    assert score is not None

    result = services.renderer.compile(
        score.lily_source, services.workdir / "assembled"
    )
    if not result.clean or result.midi_path is None:
        raise CadenzraError(
            "the assembled score does not compile cleanly even though every part "
            "did on its own: "
            + "; ".join(w.message for w in result.bar_check_warnings)
        )

    score_midi = mido.MidiFile(result.midi_path)
    if not channel_track_invariant_ok(score_midi):
        raise CadenzraError(
            "the compiled score breaks the one-voice-one-channel invariant, so "
            "per-voice analysis and per-voice performance are both unreliable"
        )
    return _check_sections(state, score_midi, services)


def render(state: PipelineState, services: ComposeServices) -> PipelineState:
    """Compile the score, interpret it, and synthesize the performance."""
    score = state.score
    plan = state.structure
    assert score is not None and plan is not None

    out = services.output_dir
    out.mkdir(parents=True, exist_ok=True)

    _log.info("compiling the final score")
    result = services.renderer.compile(score.lily_source, out / "score")
    if not result.clean or result.midi_path is None or result.pdf_path is None:
        raise CadenzraError(
            "the assembled score does not compile cleanly: "
            + "; ".join(w.message for w in result.bar_check_warnings)
            + (" (no MIDI produced)" if result.midi_path is None else "")
        )

    score_midi = mido.MidiFile(result.midi_path)

    _log.info("interpreting the performance")
    performance = interpret_performance(
        score_midi, plan, state.interpretation or _default_interpretation(state)
    )
    performance_path = out / "performance.midi"
    performance.save(performance_path)

    _log.info("rendering audio")
    audio_path = services.synthesizer.render(
        performance_path, state.spec.voices, out / "audio.wav"
    )

    lily_path = out / "score.ly"
    lily_path.write_text(score.lily_source, encoding="utf-8")

    return state.model_copy(
        update={
            "artifacts": RenderedArtifacts(
                lily_path=lily_path,
                pdf_path=result.pdf_path,
                score_midi_path=result.midi_path,
                performance_midi_path=performance_path,
                audio_path=audio_path,
            )
        }
    )


def _default_interpretation(state: PipelineState) -> InterpretationParams:
    """A style implies a groove; its defaults seed the performance stage."""
    assert state.style is not None
    return state.style.interpretation_defaults


def _check_sections(
    state: PipelineState, score_midi: mido.MidiFile, services: ComposeServices
) -> list[FeedbackItem]:
    """Cross-voice checks, per section, against the compiled score.

    The whole score is analyzed at once and sliced per section, because that is
    the artifact the compiler actually produced — re-compiling each section in
    isolation would be checking something the piece never contains.
    """
    plan = state.structure
    assert plan is not None and state.style is not None

    voices = extract_voice_notes(score_midi)
    motif_notes = _analyzed_motifs(state, services)
    feedback: list[FeedbackItem] = []
    elapsed = Fraction(0)

    for section in plan.sections:
        length = section.bars * section.meter.bar_length
        window = {
            voice_id: [
                note.model_copy(update={"onset": note.onset - elapsed})
                for note in notes
                if elapsed <= note.onset < elapsed + length
            ]
            for voice_id, notes in voices.items()
        }
        skeleton = state.harmony.get(section.section_id)
        if skeleton is not None:
            feedback += validate_section(
                window, section, skeleton, state.style, motif_notes
            )
        elapsed += length

    return feedback


def _analyzed_motifs(
    state: PipelineState, services: ComposeServices
) -> dict[MotifId, list[NoteEvent]]:
    """Each motif compiled and analyzed, so declared entries can be verified.

    This is what turns "themes that return" from a claim into a checked
    property: `validate_section` compares the realized music at each declared
    position against these notes under the declared relation (docs/03).
    """
    if state.motifs is None or state.structure is None:
        return {}

    analyzed: dict[MotifId, list[NoteEvent]] = {}
    for motif_id, motif in state.motifs.motifs.items():
        meter = _motif_meter(state, motif_id)
        scaffolded = scaffold_fragment(motif.lily_music, meter)
        try:
            result = services.renderer.compile(
                scaffolded.source, services.workdir / f"motif-{motif_id}"
            )
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


def _write_partials(state: PipelineState, output_dir: Path) -> None:
    """Everything produced so far, whether the run succeeded or failed.

    A complete record for debugging generation quality after the fact
    (docs/07), and the thing that makes a loud failure actionable rather than
    merely loud.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "state.json").write_text(
        state.model_dump_json(indent=2), encoding="utf-8"
    )
    if state.score is not None:
        (output_dir / "score.ly").write_text(state.score.lily_source, encoding="utf-8")
    if state.feedback:
        (output_dir / "feedback.json").write_text(
            json.dumps([item.model_dump(mode="json") for item in state.feedback], indent=2),
            encoding="utf-8",
        )


def build_compose_services(config: RunConfig, output_dir: Path) -> ComposeServices:
    """Wire a full run. The single composition point stays `app/factory.py`."""
    from cadenzra.app.factory import build_generator, build_renderer, build_synthesizer

    return ComposeServices(
        generator=build_generator(config),
        renderer=build_renderer(config),
        workdir=output_dir / "work",
        budgets=config.budgets,
        synthesizer=build_synthesizer(config),
        output_dir=output_dir,
    )
