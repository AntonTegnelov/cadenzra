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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import mido

from cadenzra.app.config import RunConfig
from cadenzra.app.pipeline import (
    LayerServices,
    analyzed_motifs,
    derive_style,
    feedback_dicts,
    generate_harmony,
    generate_motifs,
    plan_lyrics,
    plan_structure,
    regenerate_section_harmony,
)
from cadenzra.app.summary import write_run_summary
from cadenzra.common.errors import (
    BudgetExhaustedError,
    CadenzraError,
    LLMOutputError,
)
from cadenzra.graph.routing import cheapest_level
from cadenzra.interfaces.critique import AudioCritic, FeedbackRouter
from cadenzra.interfaces.rendering import Synthesizer
from cadenzra.model.artifacts import AssembledSection, RenderedArtifacts
from cadenzra.model.contexts import (
    LyricsContext,
    MaterialInstruction,
    PatchContext,
    VoiceContext,
)
from cadenzra.model.critique import CritiqueBrief
from cadenzra.model.feedback import FeedbackItem, FeedbackLevel
from cadenzra.model.interpretation import InterpretationParams
from cadenzra.model.lyrics import SectionLyricDirective, SectionLyrics
from cadenzra.model.primitives.ids import MotifId, SectionId, VoiceId
from cadenzra.model.primitives.meter import MeterSpec
from cadenzra.model.primitives.time import bar_containing
from cadenzra.model.review import ReviewRequest
from cadenzra.model.spec import PieceSpec, VoiceSpec
from cadenzra.model.state import PipelineState, attempt_key, voice_key
from cadenzra.model.structure import MaterialEntry, SectionPlan
from cadenzra.model.voice import VoicePart
from cadenzra.notation.assemble import assemble_score, assemble_section
from cadenzra.notation.keys import prefer_flats
from cadenzra.notation.rebar import octave_displacement, rebar_events
from cadenzra.notation.scaffold import count_bar_checks, splice_bars, split_bars
from cadenzra.performance.interpret import interpret_performance
from cadenzra.verification.audio import validate_audio_dynamics
from cadenzra.verification.lyrics import missing_devices, validate_section_lyrics
from cadenzra.verification.midi_analysis import (
    NoteEvent,
    channel_track_invariant_ok,
    extract_voice_notes,
)
from cadenzra.verification.section import validate_section
from cadenzra.verification.transposition import (
    TONAL_ANSWER_MAX_ALTERED_SHARE,
    UnknownRelationError,
    parse_relation,
)
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
    # The critic is optional: a run without one still produces every artifact,
    # it simply skips the listening pass.
    critic: AudioCritic | None = None
    router: FeedbackRouter | None = None
    # Provenance for the run summary; None (tests, harness) skips the summary.
    run_config: RunConfig | None = None
    spec_name: str | None = None


def load_resume_state(output_dir: Path, spec: PieceSpec) -> PipelineState:
    """The previous run's state, ready to resume — or a loud refusal.

    Downstream residue (assembly, score, artifacts, feedback) is cleared:
    those stages always re-run, and stale copies of them would misdescribe the
    music the resumed run is about to produce.
    """
    path = output_dir / "state.json"
    if not path.exists():
        raise CadenzraError(
            f"nothing to resume: {path} does not exist — run without --resume first"
        )
    state = PipelineState.model_validate_json(path.read_text(encoding="utf-8"))
    if state.spec != spec:
        raise CadenzraError(
            "the saved state was produced by a different spec than the one "
            "requested; delete the state or run without --resume"
        )
    return state.model_copy(
        update={"sections": {}, "score": None, "artifacts": None, "feedback": []}
    )


def compose(
    spec: PieceSpec,
    services: ComposeServices,
    *,
    initial: PipelineState | None = None,
) -> PipelineState:
    """Run the whole pipeline. Raises `CadenzraError` on an exhausted budget.

    `initial` resumes from a previous run's state: every layer skips the
    slices already present and regenerates only what is missing.
    """
    state = initial if initial is not None else PipelineState(spec=spec)
    try:
        state = derive_style(state, services)
        state = plan_structure(state, services)
        state = plan_lyrics(state, services)
        state = generate_motifs(state, services)
        state = generate_harmony(state, services)
        state = generate_voices(state, services)
        state = generate_lyrics(state, services)
        state = assemble_and_verify(state, services)
        state = render(state, services)
        state = critique(state, services)
    except CadenzraError as error:
        if error.partial_state is not None:
            state = error.partial_state
        if services.runlog is not None:
            services.runlog.note("The run failed", str(error))
        _write_partials(state, services.output_dir, run_dir=_run_dir_of(services))
        _summarize(services, spec, error=error)
        raise
    _write_partials(state, services.output_dir, run_dir=_run_dir_of(services))
    _summarize(services, spec, error=None)
    return state


def _run_dir_of(services: ComposeServices) -> Path | None:
    return services.runlog.dir if services.runlog is not None else None


def _summarize(
    services: ComposeServices, spec: PieceSpec, *, error: CadenzraError | None
) -> None:
    """Write the run summary and its index line, on success and on failure.

    Wired only when the factory filled in the provenance fields — a
    hand-assembled `ComposeServices` in a test keeps its old behavior.
    """
    if (
        services.runlog is None
        or services.run_config is None
        or services.spec_name is None
    ):
        return
    failure: dict[str, object] | None
    if error is None:
        status, failure = "completed", None
    elif isinstance(error, BudgetExhaustedError):
        status = "budget_exhausted"
        failure = {"loop_key": error.loop_key, "message": str(error)}
    else:
        status, failure = "failed", {"loop_key": None, "message": str(error)}
    write_run_summary(
        state=None,
        config=services.run_config,
        spec=spec,
        spec_name=services.spec_name,
        status=status,
        failure=failure,
        run_dir=services.runlog.dir,
        index_path=services.run_config.output_dir / "index.jsonl",
    )


def generate_voices(state: PipelineState, services: ComposeServices) -> PipelineState:
    """Every (section, voice) pair, section by section.

    Within a section voices are independent given the skeleton, so they run
    concurrently. Across sections generation is sequential per voice, because
    the sliding window needs the previous section to exist (docs/04).
    """
    plan = state.structure
    assert plan is not None
    motif_events = analyzed_motifs(state, services.renderer, services.workdir)

    for section in plan.sections:
        voice_ids = [
            voice_id
            for voice_id in _voices_in(section, state.spec)
            if voice_key(section.section_id, voice_id) not in state.voices
        ]
        if not voice_ids:
            # Everything here was written by the run being resumed.
            continue
        _log.info(
            "writing %d voices for section %s", len(voice_ids), section.section_id
        )
        results = _write_section_voices(
            state, services, section, voice_ids, motif_events
        )
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


# Texture words that mean the voices are in conversation. Free text on the
# plan, matched by substring — a branch on data, not a genre switch (docs/03).
_CONTRAPUNTAL_MARKERS = ("imitative", "fugal", "fugue", "canon", "contrapuntal", "polyphon")


def _is_contrapuntal(texture: str) -> bool:
    lowered = texture.lower()
    return any(marker in lowered for marker in _CONTRAPUNTAL_MARKERS)


def _write_section_voices(
    state: PipelineState,
    services: ComposeServices,
    section: SectionPlan,
    voice_ids: list[VoiceId],
    motif_events: dict[MotifId, list[NoteEvent]] | None = None,
) -> list[VoicePart]:
    """One section's voices — concurrent for homophony, sequential for
    counterpoint.

    Independence given the skeleton is cheap and correct where voices move
    together; in an imitative texture the *relationships* are the content, and
    four voices drawing on the same chord tones blind to each other produce
    parallels at a rate no prompt can prevent (the double-fugue's first pass:
    ~44 distinct passages). Counterpoint is written the way it always has
    been — against the lines already on the page, in entry order.

    Its own function so `state` and `section` are bound as arguments rather
    than captured by a closure over a loop variable.
    """
    if _is_contrapuntal(section.texture):
        parts: list[VoicePart] = []
        try:
            for voice_id in _entry_order(section, voice_ids):
                part = _voice_to_convergence(
                    state,
                    services,
                    section,
                    voice_id,
                    siblings=_siblings_of(state, section, voice_id),
                    motif_events=motif_events,
                )
                parts.append(part)
                state = state.model_copy(
                    update={
                        "voices": state.voices
                        | {voice_key(section.section_id, voice_id): part}
                    }
                )
        except CadenzraError as error:
            # The lines already on the page are salvage, not waste.
            error.partial_state = state
            raise
        return parts

    with ThreadPoolExecutor(max_workers=max(1, len(voice_ids))) as pool:
        futures = {
            pool.submit(
                _voice_to_convergence,
                state,
                services,
                section,
                voice_id,
                motif_events=motif_events,
            ): voice_id
            for voice_id in voice_ids
        }
        converged: list[VoicePart] = []
        first_error: CadenzraError | None = None
        for future in as_completed(futures):
            try:
                converged.append(future.result())
            except CadenzraError as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            first_error.partial_state = state.model_copy(
                update={
                    "voices": state.voices
                    | {
                        voice_key(section.section_id, part.voice_id): part
                        for part in converged
                    }
                }
            )
            raise first_error
        return converged


def _entry_order(section: SectionPlan, voice_ids: list[VoiceId]) -> list[VoiceId]:
    """Voices by their first declared entry bar; entryless voices after,
    keeping spec order — the subject is on the page before its answer."""
    first_entry = {
        entry.voice_id: entry.bar
        for entry in sorted(section.material, key=lambda e: e.bar, reverse=True)
    }
    return sorted(
        voice_ids,
        key=lambda voice_id: (
            first_entry.get(voice_id, len(section.material) + section.bars + 1),
            voice_ids.index(voice_id),
        ),
    )


def _voices_in(section: SectionPlan, spec: PieceSpec) -> list[VoiceId]:
    """Which voices sing here, resolving any group references."""
    named = section.resolved_voice_ids(spec)
    if not named:
        named = set(spec.voices_by_id)
    return [voice.voice_id for voice in spec.voices if voice.voice_id in named]


# Failed patches before falling back to a full rewrite (docs/04: "regeneration
# from scratch is the fallback when repair fails").
_PATCH_ATTEMPTS = 2


def _protected_bars(
    materials: list[MaterialInstruction], state: PipelineState
) -> set[int]:
    """Bars pinned by the voice's declared entries — never offered to a patch.

    A prescribed entry knows its exact span in the *section's* meter; the
    fallback counts the motif's own bar checks (the sanctioned token scan),
    which is only right when the meters agree.
    """
    bars: set[int] = set()
    for instruction in materials:
        if instruction.prescribed_bars:
            bars |= set(instruction.prescribed_bars)
        elif state.motifs is not None and instruction.entry.motif_id in state.motifs:
            length = max(
                1,
                count_bar_checks(state.motifs[instruction.entry.motif_id].lily_music),
            )
            bars |= set(
                range(instruction.entry.bar, instruction.entry.bar + length)
            )
    return bars


def _item_bars(item: FeedbackItem, section: SectionPlan) -> set[int] | None:
    """The bars one item names, or None when it is not bar-scoped
    (a compile failure or parser complaint indicts the whole part)."""
    if item.source == "parser" or item.location is None:
        return None
    start = bar_containing(item.location, section.meter)
    end = bar_containing(item.span[1], section.meter) if item.span else start
    return set(range(start, end + 1))


def _flagged_bars(
    feedback: list[FeedbackItem], section: SectionPlan
) -> set[int] | None:
    """The bars the feedback names, or None when any item is not bar-scoped."""
    flagged: set[int] = set()
    for item in feedback:
        bars = _item_bars(item, section)
        if bars is None:
            return None
        flagged |= bars
    return flagged


def _offered_feedback(
    feedback: list[FeedbackItem],
    editable: tuple[int, ...],
    section: SectionPlan,
) -> list[FeedbackItem]:
    """The items a patch can act on: those touching a bar it was offered.

    A complaint pinned entirely to a bar outside the offer belongs to some
    other repair; quoting it steers the patch at music it cannot touch (the
    double-fugue's patches were told about the prescribed entry bar on every
    attempt). Only the prompt is filtered — the loop keeps the full list,
    because convergence is measured against everything. Every item here is
    bar-scoped: `_editable_bars` returns () otherwise, and () never patches.
    """
    allowed = set(editable)
    kept = []
    for item in feedback:
        bars = _item_bars(item, section)
        assert bars is not None  # guaranteed by _editable_bars
        if bars & allowed:
            kept.append(item)
    return kept


def _splice_prescriptions(
    part: VoicePart, materials: list[MaterialInstruction]
) -> VoicePart:
    """A part carries its prescribed entries verbatim, mechanically.

    The prompt hands the finished bars over, and a live rewrite under a wall
    of cross-voice complaints still paraphrased them — three entries broken
    in one sweep, taking the pinned-grid and entry-check guarantees with
    them. The bars are not the model's to write, so they are not left to the
    model to copy. Only complete bars are spliced: a prescription ending
    mid-bar leaves its final bar to the composer, exactly as the prompt
    says. Splicing is skipped where the part is too short to hold the span —
    the validators own that failure.
    """
    total = count_bar_checks(part.lily_music)
    replacements: dict[int, str] = {}
    for instruction in materials:
        text = instruction.prescribed_lily
        if text is None or not instruction.prescribed_bars or "|" not in text:
            continue
        # Prescriptions come from `rebar_events`, which never writes quoted
        # pipes or \bar commands — the plain rindex is safe on this text.
        complete = text[: text.rindex("|") + 1]
        bars = split_bars(complete)
        targets = instruction.prescribed_bars[: len(bars)]
        if not targets or targets[-1] > total:
            continue
        for bar, content in zip(targets, bars, strict=False):
            replacements[bar] = content.strip()
    if not replacements:
        return part
    return part.model_copy(
        update={"lily_music": splice_bars(part.lily_music, replacements)}
    )


def _entry_aware(
    feedback: list[FeedbackItem],
    section: SectionPlan,
    materials: list[MaterialInstruction],
) -> list[FeedbackItem]:
    """Feedback with the prescription attached where it lands on an entry.

    A range or rhythm complaint inside a prescribed entry's bars reads as
    "move these notes" — an order the entry check countermands. Naming the
    entry and quoting its finished bars turns the contradiction into an
    answer: write exactly this. Items with no bar to pin stay untouched.
    """
    prescribed = [
        instruction
        for instruction in materials
        if instruction.prescribed_lily is not None
    ]
    if not prescribed:
        return feedback
    decorated = []
    for item in feedback:
        bars = _item_bars(item, section)
        hit = next(
            (
                instruction
                for instruction in prescribed
                if bars is not None and bars & set(instruction.prescribed_bars)
            ),
            None,
        )
        if hit is None:
            decorated.append(item)
            continue
        first, last = hit.prescribed_bars[0], hit.prescribed_bars[-1]
        where = f"bar {first}" if first == last else f"bars {first}-{last}"
        decorated.append(
            item.model_copy(
                update={
                    "message": (
                        f"{item.message} ({where} is the prescribed "
                        f"{hit.motif.role} entry — write it exactly as: "
                        f"{hit.prescribed_lily})"
                    )
                }
            )
        )
    return decorated


def _editable_bars(
    feedback: list[FeedbackItem],
    rejected: VoicePart | None,
    section: SectionPlan,
    protected: set[int],
) -> tuple[int, ...]:
    """The bars a patch may rewrite, or () when only a full rewrite can help.

    Empty when there is nothing to patch against, when any item is not
    bar-scoped, or when every flagged bar is prescribed.
    """
    if rejected is None or not feedback:
        return ()
    flagged = _flagged_bars(feedback, section)
    if flagged is None:
        return ()
    total = count_bar_checks(rejected.lily_music)
    return tuple(
        bar for bar in sorted(flagged - protected) if 1 <= bar <= total
    )


def _voice_to_convergence(
    state: PipelineState,
    services: ComposeServices,
    section: SectionPlan,
    voice_id: VoiceId,
    *,
    prior: list[FeedbackItem] | None = None,
    siblings: dict[VoiceId, str] | None = None,
    motif_events: dict[MotifId, list[NoteEvent]] | None = None,
) -> VoicePart:
    """One fragment, regenerated against its feedback until it validates.

    `prior` seeds the first attempt with feedback from a *later* layer — the
    cross-voice checks — which the fragment on its own would always pass.

    Bar-scoped feedback repairs by *patch*: only the flagged, unprescribed
    bars are offered for rewriting, spliced deterministically into the
    rejected part. That shrinks output to the changed bars and makes breaking
    a prescribed entry mechanically impossible. After `_PATCH_ATTEMPTS`
    failed patches, full regeneration is the fallback — which is what
    docs/04 promised all along.

    LilyPond reports only the first failed bar check per compile, so a part
    with several bad bars is discovered one bar at a time. The permission
    model makes attribution exact: a spliced patch can only have touched the
    bars it was offered, so when the next compile flags only bars it was
    never offered, the patch did its job and the compile revealed a defect
    that was already there. Such a cycle consumes no retry budget — the
    reveals are bounded by the bars on the page.
    """
    voice_spec = state.spec.voices_by_id[voice_id]
    materials = _materials_for(state, section, voice_id, motif_events)
    tail = _previous_tail(state, section, voice_id)
    feedback = _entry_aware(list(prior or []), section, materials)
    rejected: VoicePart | None = (
        state.voices.get(voice_key(section.section_id, voice_id)) if prior else None
    )
    protected = _protected_bars(materials, state)
    patch_attempts = 0
    offered: set[int] = set()  # bars ever offered against the current part text
    attempt = 0
    cycle = 0

    while attempt < services.budgets.voice:
        cycle += 1
        shown = {item.fingerprint() for item in feedback}
        editable = _editable_bars(feedback, rejected, section, protected)
        patching = bool(editable) and patch_attempts < _PATCH_ATTEMPTS
        if not patching:
            attempt += 1
        try:
            if patching:
                assert rejected is not None  # _editable_bars requires it
                patch = services.generator.patch_voice(
                    PatchContext(
                        section=section,
                        voice=voice_spec,
                        skeleton=state.harmony.get(section.section_id),
                        part=rejected,
                        editable_bars=editable,
                        feedback=_offered_feedback(feedback, editable, section),
                        siblings=siblings or {},
                    )
                )
                part = rejected.model_copy(
                    update={
                        "lily_music": splice_bars(rejected.lily_music, patch)
                    }
                )
            else:
                # A fresh part: bar numbers from the old text no longer apply.
                offered = set()
                part = services.generator.generate_voice(
                    VoiceContext(
                        section=section,
                        voice=voice_spec,
                        style=state.style,  # type: ignore[arg-type]
                        skeleton=state.harmony.get(section.section_id),
                        materials=materials,
                        previous_tail=tail[0] if tail else None,
                        previous_meter=tail[1] if tail else None,
                        rejected=rejected,
                        feedback=feedback,
                        siblings=siblings or {},
                    )
                )
                part = _splice_prescriptions(part, materials)
        except LLMOutputError as error:
            # Unparseable output is a rejection whose diagnosis is already
            # written; the next attempt gets it verbatim rather than the run
            # ending over something a retry could fix.
            if patching:
                attempt += 1
                patch_attempts += 1
            feedback = _malformed("voice", section.section_id, voice_id, error)
            _log.warning(
                "%s in section %s came back malformed on attempt %d/%d: %s",
                voice_id,
                section.section_id,
                attempt,
                services.budgets.voice,
                error,
            )
            continue

        feedback = _entry_aware(
            validate_voice(
                part,
                voice_spec,
                section,
                services.renderer,
                services.workdir / f"{section.section_id}-{voice_id}-{cycle}",
            ),
            section,
            materials,
        )
        if not feedback:
            return part
        if patching:
            revealed = _flagged_bars(feedback, section)
            if revealed is None or not revealed.isdisjoint(offered | set(editable)):
                # An offered bar still fails, or the part no longer even
                # compiles: the cycle pays. But a patch that cleared *some*
                # of its bars is working, not failing — a live run repaired
                # six of seven offered bars and the one stubborn bar tripped
                # the fallback, which threw all six repairs away. Only a
                # patch that clears nothing is a strike.
                attempt += 1
                cleared_any = revealed is not None and bool(
                    set(editable) - revealed
                )
                if not cleared_any:
                    patch_attempts += 1
            offered |= set(editable)
            rejected = part
        elif shown and {item.fingerprint() for item in feedback} == shown:
            # The rewrite reproduced its own rejection — shown its old text
            # under "change as little as possible", the model copies it,
            # mistake included. The next attempt starts from scratch: the
            # feedback is kept, the copyable text is not (docs/04).
            rejected = None
        else:
            rejected = part
        _log.warning(
            "%s in section %s failed on attempt %d/%d: %s",
            voice_id,
            section.section_id,
            attempt,
            services.budgets.voice,
            "; ".join(item.message for item in feedback),
        )
        if services.runlog is not None:
            services.runlog.validation(
                what=f"the {voice_id} part for section {section.section_id}",
                loop_key=attempt_key("voice", section.section_id, voice_id),
                attempt=cycle,
                budget=services.budgets.voice,
                messages=[item.message for item in feedback],
                items=feedback_dicts(feedback, {section.section_id: section.meter}),
            )

    raise BudgetExhaustedError(
        f"the {voice_id} part for section {section.section_id} still fails after "
        f"{services.budgets.voice} attempts: "
        + "; ".join(item.message for item in feedback),
        loop_key=attempt_key("voice", section.section_id, voice_id),
        attempts=services.budgets.voice,
    )


def generate_lyrics(
    state: PipelineState, services: ComposeServices, only: set[SectionId] | None = None
) -> PipelineState:
    """Write the words, one section at a time, after that section's music.

    One call per section covering every singing voice — which is the entire
    coordination mechanism (docs/10). Sequential across sections so each one
    can read what has already been sung.

    `only` re-runs named sections, for when cross-voice checks have replaced
    the music the words were written to.
    """
    lyric_plan = state.lyric_plan
    plan = state.structure
    assert plan is not None
    if lyric_plan is None:
        return state

    directives = lyric_plan.by_section
    written: dict[SectionId, SectionLyrics] = dict(state.lyrics)
    parts: dict[str, VoicePart] = dict(state.voices)

    for section in plan.sections:
        if only is not None and section.section_id not in only:
            continue
        if only is None and section.section_id in written:
            # A resumed run's earlier sections keep their words; `only` is the
            # explicit request to rewrite them after their music changed.
            continue
        directive = directives.get(section.section_id)
        voice_ids = _singing_voices_in(section, state.spec)
        if directive is None or not voice_ids:
            continue

        _log.info("writing words for section %s", section.section_id)
        lyrics = _lyrics_to_convergence(
            state,
            services,
            section,
            directive,
            voice_ids,
            previous=[
                written[item.section_id]
                for item in plan.sections
                if item.section_id in written and item.section_id != section.section_id
            ],
            refrain_source=written.get(directive.refrain_of)
            if directive.refrain_of
            else None,
        )
        written[section.section_id] = lyrics
        # The words become part of the score through the part that carries
        # them: assembly reads `VoicePart.lily_lyrics` and knows nothing about
        # the lyric layer.
        for voice in lyrics.voices:
            key = voice_key(section.section_id, voice.voice_id)
            parts[key] = parts[key].model_copy(
                update={"lily_lyrics": voice.lily_lyrics}
            )

    return state.model_copy(update={"lyrics": written, "voices": parts})


def _lyrics_to_convergence(
    state: PipelineState,
    services: ComposeServices,
    section: SectionPlan,
    directive: SectionLyricDirective,
    voice_ids: list[VoiceId],
    *,
    previous: list[SectionLyrics],
    refrain_source: SectionLyrics | None,
) -> SectionLyrics:
    """One section's words, regenerated against their feedback until they hold."""
    lyric_plan = state.lyric_plan
    assert lyric_plan is not None

    feedback: list[FeedbackItem] = []
    rejected: SectionLyrics | None = None

    for attempt in range(1, services.budgets.lyric + 1):
        ctx = LyricsContext(
            section=section,
            directive=directive,
            language=lyric_plan.language,
            story=lyric_plan.story,
            voice_ids=voice_ids,
            parts={
                voice_id: state.voice_part(section.section_id, voice_id)
                for voice_id in voice_ids
            },
            previous=previous,
            refrain_source=refrain_source,
            rejected=rejected,
            feedback=feedback,
        )
        try:
            lyrics = services.generator.generate_lyrics(ctx)
        except LLMOutputError as error:
            feedback = _malformed("lyric", section.section_id, None, error)
            _log.warning(
                "the words for section %s came back malformed on attempt %d/%d: %s",
                section.section_id,
                attempt,
                services.budgets.lyric,
                error,
            )
            continue

        feedback = validate_section_lyrics(
            lyrics,
            directive,
            section,
            ctx.parts,
            language=lyric_plan.language,
            renderer=services.renderer,
            workdir=services.workdir / f"{section.section_id}-lyrics-{attempt}",
            refrain_source=refrain_source,
        )
        if not feedback:
            # Craft is asked about only once the contracts hold, and asked
            # blind: a reader told what to find reports finding it (docs/10).
            # One nudge, not a budget: whether a device landed is a judgment,
            # and spending every attempt on a judgment call would starve the
            # checks that are actually decidable.
            advisory = (
                _observe_devices(services, lyrics, directive, section)
                + _review_craft(services, lyrics, section)
                if attempt == 1
                else []
            )
            if not advisory:
                return lyrics
            feedback = advisory
        rejected = lyrics
        _log.warning(
            "the words for section %s failed on attempt %d/%d: %s",
            section.section_id,
            attempt,
            services.budgets.lyric,
            "; ".join(item.message for item in feedback),
        )
        if services.runlog is not None:
            services.runlog.validation(
                what=f"the words for section {section.section_id}",
                loop_key=attempt_key("lyric", section.section_id, None),
                attempt=attempt,
                budget=services.budgets.lyric,
                messages=[item.message for item in feedback],
                items=feedback_dicts(feedback, {section.section_id: section.meter}),
            )

    raise BudgetExhaustedError(
        f"the words for section {section.section_id} still fail after "
        f"{services.budgets.lyric} attempts: "
        + "; ".join(item.message for item in feedback),
        loop_key=attempt_key("lyric", section.section_id, None),
        attempts=services.budgets.lyric,
    )


def _malformed(
    level: FeedbackLevel,
    section_id: SectionId | None,
    voice_id: VoiceId | None,
    error: LLMOutputError,
) -> list[FeedbackItem]:
    """A parse failure, as routable feedback.

    Quoted rather than paraphrased: the parser already knows exactly what was
    wrong, and a guessed diagnosis sends the regeneration looking in the wrong
    place (docs/05).
    """
    return [
        FeedbackItem(
            source="parser",
            level=level,
            section_id=section_id,
            voice_id=voice_id,
            message=str(error),
        )
    ]


def _review_craft(
    services: ComposeServices,
    lyrics: SectionLyrics,
    section: SectionPlan,
) -> list[FeedbackItem]:
    """One blinded craft question about the finished words (docs/10).

    The question names neither the theme, the devices nor the scheme — the
    blinding that made the device observer's verdicts agree with a human
    reading. Advisory like the device check: a rough line is worth one more
    attempt, never a veto.
    """
    text = "\n".join(
        f"{voice.voice_id}: " + " / ".join(line.text for line in voice.lines)
        for voice in lyrics.voices
    )
    verdict = services.generator.review(
        ReviewRequest(
            question=(
                "Read these lyrics as a stranger to the piece. Is any line "
                "awkward to say or sing, unclear in its meaning, or out of "
                "register with the lines around it? Name the line and what "
                "stumbles."
            ),
            subject=text,
        )
    )
    if verdict.acceptable:
        return []
    notes = verdict.reasons + verdict.suggestions
    return [
        FeedbackItem(
            source="review",
            level="lyric",
            section_id=section.section_id,
            kind="review",
            message="a blind reading stumbled: " + "; ".join(notes or ["no detail given"]),
        )
    ]


def _observe_devices(
    services: ComposeServices,
    lyrics: SectionLyrics,
    directive: SectionLyricDirective,
    section: SectionPlan,
) -> list[FeedbackItem]:
    """Ask a blind reader what craft is in the words, and compare here.

    Advisory: a device nobody noticed is worth another attempt, but never a
    veto — the deterministic checks are what decide (docs/05).
    """
    if not directive.devices:
        return []

    text = "\n\n".join(
        f"{voice.voice_id}:\n" + voice.text for voice in lyrics.voices
    )
    observations = services.generator.observe_lyric_devices(text)
    missing = missing_devices(directive, observations)
    if not missing:
        return []
    return [
        FeedbackItem(
            source="observe_lyric_devices",
            level="lyric",
            section_id=section.section_id,
            message=(
                f"section {section.section_id} was written to use "
                + ", ".join(missing)
                + ", and a reader who did not know that found no sign of "
                + ("them" if len(missing) > 1 else "it")
            ),
        )
    ]


def _singing_voices_in(section: SectionPlan, spec: PieceSpec) -> list[VoiceId]:
    """The voices active in this section that sing."""
    singing = {voice.voice_id for voice in spec.singing_voices}
    return [
        voice_id for voice_id in _voices_in(section, spec) if voice_id in singing
    ]


def _materials_for(
    state: PipelineState,
    section: SectionPlan,
    voice_id: VoiceId,
    motif_events: dict[MotifId, list[NoteEvent]] | None = None,
) -> list[MaterialInstruction]:
    if state.motifs is None:
        return []
    plan = state.structure
    instructions = []
    for entry in section.material:
        if entry.voice_id != voice_id or entry.motif_id not in state.motifs:
            continue
        prescribed: str | None = None
        prescribed_bars: tuple[int, ...] = ()
        adjustable = 0
        events = (motif_events or {}).get(entry.motif_id) or []
        if events:
            prescribed, prescribed_bars, adjustable = _prescribed_entry(
                entry, events, state.spec.voices_by_id[voice_id], section
            )
        instructions.append(
            MaterialInstruction(
                motif=state.motifs[entry.motif_id],
                entry=entry,
                home_meter=(
                    plan.meter_declaring(entry.motif_id)
                    if plan is not None
                    else None
                ),
                prescribed_lily=prescribed,
                prescribed_bars=prescribed_bars,
                max_adjustable=adjustable,
            )
        )
    return instructions


def _prescribed_entry(
    entry: MaterialEntry,
    events: list[NoteEvent],
    voice: VoiceSpec,
    section: SectionPlan,
) -> tuple[str | None, tuple[int, ...], int]:
    """The entry rendered ready to copy, its bar span, and its license.

    Everything about a declared entry is determined: pitches and rhythm by
    the motif, the transform by the plan, and the register up to a whole
    octave — which every downstream check is blind to, so it is chosen here
    to fit the voice. Handing over the finished bars is the doctrine the
    surface already states ("hand over the answer rather than the puzzle");
    30 identical live failures measured what withholding them costs.
    """
    try:
        relation = parse_relation(entry.relation)
    except UnknownRelationError:
        return None, (), 0  # the structure validator owns this failure
    adjustable = 0
    if relation.kind == "tonal answer":
        # The literal real answer: a fifth up, zero adjustments — which the
        # checker accepts, and the license below keeps the tonal option open.
        shift = 7
        adjustable = max(1, int(len(events) * TONAL_ANSWER_MAX_ALTERED_SHARE))
    elif relation.kind == "transposition":
        shift = relation.semitones
    else:
        shift = 0
    if relation.kind == "inversion":
        first = events[0].midi_pitch
        realized = [
            event.model_copy(update={"midi_pitch": 2 * first - event.midi_pitch})
            for event in events
        ]
    else:
        realized = [
            event.model_copy(update={"midi_pitch": event.midi_pitch + shift})
            for event in events
        ]
    displacement = octave_displacement(
        [event.midi_pitch for event in realized], voice.range_low, voice.range_high
    )
    if displacement is None:
        raise CadenzraError(
            f"the {entry.motif_id!r} entry for {voice.voice_id} fits no "
            "whole-octave placement inside "
            f"{voice.range_low.to_scientific()}–{voice.range_high.to_scientific()}"
            " — the motif validator should have rejected this library"
        )
    base = min(event.onset for event in realized)
    placed = [
        event.model_copy(
            update={
                "midi_pitch": event.midi_pitch + displacement,
                "onset": event.onset - base,
            }
        )
        for event in realized
    ]
    text = rebar_events(
        placed, section.meter, prefer_flats=prefer_flats(section.key)
    )
    if text is None:
        _log.info(
            "the %s entry for %s is not rebarrable (tuplets); falling back to "
            "instruction text",
            entry.motif_id,
            voice.voice_id,
        )
        return None, (), adjustable
    total = max(event.onset + event.duration for event in placed)
    span = -(-total // section.meter.bar_length)  # ceil
    return text, tuple(range(entry.bar, entry.bar + int(span))), adjustable


def _previous_tail(
    state: PipelineState, section: SectionPlan, voice_id: VoiceId
) -> tuple[str, MeterSpec] | None:
    """The last few bars this voice sang, and the meter they were written in,
    so its line connects across the seam without teaching the old bar length
    by example."""
    plan = state.structure
    assert plan is not None
    order = [item.section_id for item in plan.sections]
    index = order.index(section.section_id)
    for previous in reversed(plan.sections[:index]):
        part = state.voices.get(voice_key(previous.section_id, voice_id))
        if part is not None:
            # `split_bars`, not a naive split("|"): a quoted `\bar "|:"` would
            # shift a naive count and hand the model the wrong bars.
            bars = split_bars(part.lily_music)
            return "".join(bars[-_SLIDING_WINDOW_BARS:]).strip(), previous.meter
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
    trajectory: list[int] = []
    regridded: set[SectionId] = set()
    for attempt in range(1, services.budgets.section + 1):
        state = assemble(state, services)
        feedback = _verify_assembled(state, services)
        if not feedback:
            return state
        unfixable = [item for item in feedback if item.routing == "unfixable"]
        if unfixable:
            # A pinned held tone indicts the grid, and the grid can move —
            # once per section, with the violation quoted, before the loud
            # path. Anything else routed unfixable (two prescribed lines in
            # parallel) has no layer left to loop back to.
            regriddable = [
                item
                for item in unfixable
                if item.kind == "held_tone"
                and item.section_id is not None
                and item.section_id not in regridded
            ]
            if not regriddable or len(regriddable) < len(unfixable):
                _raise_unfixable(unfixable, services)
            state = _regrid(state, services, regriddable)
            regridded |= {
                item.section_id
                for item in regriddable
                if item.section_id is not None
            }
            continue

        # A repair sweep that does not shrink the set of distinct faults will
        # not shrink it next time either — measured: 263 → 63 → 66, with the
        # third sweep spending thirteen minutes proving what the second had.
        distinct = len({item.fingerprint() for item in feedback})
        trajectory.append(distinct)
        if len(trajectory) >= 2 and distinct >= trajectory[-2]:
            path = " -> ".join(str(count) for count in trajectory)
            raise BudgetExhaustedError(
                f"the cross-voice checks stopped converging: distinct "
                f"violations went {path}; still failing: "
                + "; ".join(item.message for item in feedback),
                loop_key=attempt_key("section", None, None),
                attempts=attempt,
            )

        targets = _targets_of(feedback)
        _log.warning(
            "cross-voice checks failed on attempt %d/%d: %s",
            attempt,
            services.budgets.section,
            "; ".join(item.message for item in feedback),
        )
        if services.runlog is not None:
            services.runlog.validation(
                what="the cross-voice checks",
                loop_key=attempt_key("section", None, None),
                attempt=attempt,
                budget=services.budgets.section,
                messages=[item.message for item in feedback],
                items=feedback_dicts(feedback, _section_meters(state)),
            )
        if not targets:
            break
        state = _rewrite_voices(state, services, feedback, targets)
        # The words were written to music that no longer exists. Notation is
        # the source of truth; everything downstream of it rebuilds (docs/10).
        rewritten = {section_id for section_id, _ in targets}
        if state.lyric_plan is not None:
            state = generate_lyrics(state, services, only=rewritten)

    raise BudgetExhaustedError(
        "the assembled score still fails cross-voice checks after "
        f"{services.budgets.section} attempts: "
        + "; ".join(item.message for item in feedback),
        loop_key=attempt_key("section", None, None),
        attempts=services.budgets.section,
    )


# The most complaints one repair prompt carries. The double-fugue handed a
# voice 45 at once; a voice asked to fix 45 relationships fixes none of them
# well. Priority is structural: an entry violation outranks a held tone
# outranks a parallel.
_MAX_COMPLAINTS = 8
_KIND_PRIORITY = {"entry": 0, "held_tone": 1, "parallels": 2}


def _prioritized(items: list[FeedbackItem]) -> list[FeedbackItem]:
    """At most `_MAX_COMPLAINTS` items, most structural first, rest announced.

    Stable within each class, and honest about the cut: the synthetic tail
    note says more are waiting so the model does not mistake eight complaints
    for the whole picture.
    """
    if len(items) <= _MAX_COMPLAINTS:
        return items
    ranked = sorted(
        items, key=lambda item: _KIND_PRIORITY.get(item.kind or "", 3)
    )
    kept = ranked[:_MAX_COMPLAINTS]
    dropped = len(items) - len(kept)
    return [
        *kept,
        FeedbackItem(
            source="router",
            level=kept[0].level,
            section_id=kept[0].section_id,
            voice_id=kept[0].voice_id,
            message=(
                f"…and {dropped} more; fix these first — the rest will be "
                "re-checked after the rewrite"
            ),
        ),
    ]


def _regrid(
    state: PipelineState, services: ComposeServices, items: list[FeedbackItem]
) -> PipelineState:
    """The grid moves where no voice can.

    The named sections' harmony regenerates with the violations quoted and an
    instruction the plan can act on; assembly then re-judges everything
    against the new grid. The regenerated grid passes the entries check
    before acceptance, so a model that cannot satisfy the pinned note fails
    loudly in the harmony loop rather than bouncing back here.
    """
    by_section: dict[SectionId, list[FeedbackItem]] = {}
    for item in items:
        assert item.section_id is not None  # caller filtered
        by_section.setdefault(item.section_id, []).append(item)
    for section_id, section_items in by_section.items():
        prior = [
            item.model_copy(
                update={
                    "level": "harmony",
                    "message": (
                        item.message
                        + ". The held note is prescribed by the plan and cannot "
                        "change — choose this section's chords so the chord at "
                        "that point contains it."
                    ),
                }
            )
            for item in section_items
        ]
        _log.warning(
            "no voice is free to fix section %s; regenerating its harmony: %s",
            section_id,
            "; ".join(item.message for item in section_items),
        )
        if services.runlog is not None:
            services.runlog.note(
                f"The grid moves for section {section_id}",
                "No voice named by these violations is free to move, so the "
                "harmony regenerates with the evidence:\n"
                + "; ".join(item.message for item in section_items),
            )
        state = regenerate_section_harmony(state, services, section_id, prior)
    return state


def _raise_unfixable(
    unfixable: list[FeedbackItem], services: ComposeServices
) -> None:
    """A plan-level contradiction ends the run now, not after the budget.

    An item routed "unfixable" names only prescribed material on every side —
    the double-fugue's immortal D#4 spent three full repair sweeps on exactly
    this shape. `_targets_of` drops voiceless items by design, so without this
    check the contradiction would burn the budget silently. The regrid
    loop-back handles the held-tone class; this is the loud path for the
    rest, and for a section whose grid already moved once.
    """
    detail = "; ".join(item.message for item in unfixable)
    if services.runlog is not None:
        services.runlog.note(
            "A plan-level contradiction",
            "No voice named by these violations is free to move — the plan "
            f"prescribes every side of them:\n{detail}",
        )
    raise BudgetExhaustedError(
        "the score has violations no voice is free to fix — the plan "
        f"prescribes every side of them: {detail}",
        loop_key=attempt_key("section", None, None),
        attempts=0,
    )


def _section_meters(state: PipelineState) -> dict[SectionId, MeterSpec]:
    """Each section's meter, for turning feedback offsets into bar numbers."""
    assert state.structure is not None
    return {section.section_id: section.meter for section in state.structure.sections}


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
    motif_events = analyzed_motifs(state, services.renderer, services.workdir)

    for (section_id, voice_id), items in targets.items():
        _log.info("rewriting %s in section %s", voice_id, section_id)
        part = _voice_to_convergence(
            state.model_copy(update={"feedback": feedback}),
            services,
            sections[section_id],
            voice_id,
            prior=_prioritized(items),
            siblings=_siblings_of(state, sections[section_id], voice_id),
            motif_events=motif_events,
        )
        # Accumulated, not collected: the next voice to be repaired has to see
        # this one's new line. Rewriting every named voice against the same
        # stale snapshot means each avoids the others' *old* music, and the new
        # pair can be exactly as parallel — measured, a repair loop did 239
        # violations, then 48, then 48 again, and gave up.
        state = state.model_copy(
            update={"voices": state.voices | {voice_key(section_id, voice_id): part}}
        )

    return state


def _siblings_of(
    state: PipelineState, section: SectionPlan, voice_id: VoiceId
) -> dict[VoiceId, str]:
    """The other voices' music in this section, as far as it exists.

    On a cross-voice repair every sibling is present; during sequential
    contrapuntal generation only the already-written entries are — which is
    exactly what the next voice should see.
    """
    return {
        other: state.voices[voice_key(section.section_id, other)].lily_music
        for other in _voices_in(section, state.spec)
        if other != voice_id
        and voice_key(section.section_id, other) in state.voices
        and voice_key(section.section_id, other) in state.voices
    }


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


def critique(state: PipelineState, services: ComposeServices) -> PipelineState:
    """Listen to the rendered performance and act on the cheapest thing heard.

    The critique loop gets a stricter budget than the others because it is the
    most expensive and least precise: its purpose is catching gross problems,
    not converging on taste (docs/02). Interpretation adjustments get their own
    budget because they are cheap — a re-render, not a regeneration — which is
    exactly the trade the score/performance split was bought for.
    """
    if services.critic is None or services.router is None:
        return state

    plan = state.structure
    assert plan is not None

    for attempt in range(1, services.budgets.interpretation + 1):
        artifacts = state.artifacts
        assert artifacts is not None

        # The decidable half first: whether the performance stage shaped the
        # sound at all is a measurement, and measurements beat opinions.
        measured = validate_audio_dynamics(
            artifacts.audio_path, artifacts.performance_midi_path, plan
        )

        _log.info("listening to the performance")
        verdict = services.critic.critique(artifacts.audio_path, _brief(state))
        items = [*measured, *services.router.localize(verdict, plan)]
        if services.runlog is not None:
            services.runlog.note(
                "What the critic heard",
                verdict.overall
                + ("" if not items else "\n\n" + "\n".join(
                    f"- [{item.level}] {item.message}" for item in items
                )),
            )
        if verdict.acceptable and not items:
            _log.info("the critic is satisfied")
            return state.model_copy(update={"feedback": []})

        level = cheapest_level(items)
        _log.info("the critic raised %d point(s); cheapest target is %s", len(items), level)

        if level not in ("render", "interpretation"):
            # Anything costlier than a re-render means regenerating music that
            # already passed every deterministic check, on the weakest evidence
            # in the system. Recording it is the honest outcome: the run is
            # complete, and a human can read what the critic thought.
            _log.info("the remaining concerns need a human ear; recording them")
            return state.model_copy(update={"feedback": items})

        adjusted = adjust_interpretation(state, items)
        if adjusted is None:
            _log.info("no parameter change would address this; recording it")
            return state.model_copy(update={"feedback": items})

        _log.info("re-rendering with adjusted interpretation (%d/%d)",
                  attempt, services.budgets.interpretation)
        state = render(adjusted, services)

    return state.model_copy(update={"feedback": []})


def adjust_interpretation(
    state: PipelineState, items: list[FeedbackItem]
) -> PipelineState | None:
    """Turn a performance complaint into a parameter change.

    This is what the score/performance split is for: "sounds flat" becomes a
    larger dynamics range, not a rewritten note (docs/02, docs/05). Returns
    None when nothing here would move the knob, so the caller does not
    re-render identically and call it progress.
    """
    current = state.interpretation or InterpretationParams()
    text = " ".join(item.message.lower() for item in items)

    intensity = current.dynamics_curve_intensity
    if any(word in text for word in ("flat", "lifeless", "unvarying", "no dynamic")):
        intensity = min(2.0, intensity * 1.5)
    elif any(word in text for word in ("extreme", "too loud", "overpowering")):
        intensity = max(0.25, intensity * 0.6)

    if intensity == current.dynamics_curve_intensity:
        return None

    _log.info(
        "adjusting the dynamics curve from %.2f to %.2f", 
        current.dynamics_curve_intensity,
        intensity,
    )
    return state.model_copy(
        update={
            "interpretation": current.model_copy(
                update={"dynamics_curve_intensity": intensity}
            )
        }
    )


def _brief(state: PipelineState) -> CritiqueBrief:
    """What the critic needs in order to *place* what it hears — and no more.

    docs/05 says the intent summary goes to the critic alongside the audio.
    Measured against a real model, that instruction is actively harmful: given
    a performance rendered at one constant velocity with no expression at all,
    a critic briefed on the intended arc reported hearing a "powerful ff
    climax… realized with clarity", while the same critic given the same audio
    and a brief with the intentions removed said nothing about dynamics and
    described only the meter and counterpoint. Telling a listener what to
    expect makes it report hearing that.

    So the brief carries structural facts — the section labels, meters and
    voice names an observation needs in order to be localizable — and withholds
    the intentions the critic is supposed to be independently checking. The one
    intent-versus-reality question that is decidable, whether the dynamic arc
    landed, is answered by measuring the waveform instead
    (`verification/audio.py`).
    """
    plan = state.structure
    assert plan is not None
    return CritiqueBrief(
        title=state.spec.title,
        intent="",
        form_summary="",
        sections=[
            f"{section.section_id}: {section.bars} bars of "
            f"{section.meter.surface_string()}"
            for section in plan.sections
        ],
        voices=[voice.voice_id for voice in state.spec.voices],
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
    motif_notes = analyzed_motifs(state, services.renderer, services.workdir)
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




def _write_partials(
    state: PipelineState, output_dir: Path, *, run_dir: Path | None = None
) -> None:
    """Everything produced so far, whether the run succeeded or failed.

    A complete record for debugging generation quality after the fact
    (docs/07), and the thing that makes a loud failure actionable rather than
    merely loud. The run dir gets its own copy of the state: the spec-level
    one is clobbered by every re-run, which is how the double-fugue autopsy
    lost the structure plan it needed.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    state_json = state.model_dump_json(indent=2)
    (output_dir / "state.json").write_text(state_json, encoding="utf-8")
    if run_dir is not None:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "state.json").write_text(state_json, encoding="utf-8")
    if state.score is not None:
        (output_dir / "score.ly").write_text(state.score.lily_source, encoding="utf-8")
    if state.feedback:
        (output_dir / "feedback.json").write_text(
            json.dumps([item.model_dump(mode="json") for item in state.feedback], indent=2),
            encoding="utf-8",
        )


def build_compose_services(
    config: RunConfig,
    output_dir: Path,
    *,
    with_critic: bool = True,
    spec_name: str | None = None,
) -> ComposeServices:
    """Wire a full run. The single composition point stays `app/factory.py`."""
    from cadenzra.app.factory import (
        build_critic,
        build_generator,
        build_renderer,
        build_synthesizer,
        open_run_log,
    )

    # First, before any layer runs: the log has to exist by the time the first
    # prompt goes out, and a run that dies early is one whose log matters.
    runlog = open_run_log(config, output_dir)
    critic = build_critic(config, runlog) if with_critic else None
    return ComposeServices(
        generator=build_generator(config, runlog),
        renderer=build_renderer(config, runlog),
        workdir=output_dir / "work",
        budgets=config.budgets,
        runlog=runlog,
        synthesizer=build_synthesizer(config),
        output_dir=output_dir,
        critic=critic,
        router=critic,
        run_config=config,
        spec_name=spec_name or output_dir.name,
    )
