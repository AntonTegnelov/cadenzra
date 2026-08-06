"""The live harness: measuring prompt quality instead of guessing at it.

Prompt quality can only be verified against real models, so this runs single
capabilities live — "generate one part in 7/8 against this skeleton, ten
trials" — and reports pass rates through the *real* validators. This is where
prompt iteration happens with measured feedback rather than vibes, and where
surface design is A/B-tested, because "intuitive" is an empirical claim
(docs/08 principle 2, docs/09).
"""

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from cadenzra.app.config import RunConfig
from cadenzra.app.factory import build_generator, build_renderer, open_run_log
from cadenzra.common.errors import CadenzraError
from cadenzra.graph.nodes import build_voice_context
from cadenzra.model.harmony import HarmonicEvent, HarmonicSkeleton
from cadenzra.model.primitives.ids import SectionId, VoiceId
from cadenzra.model.primitives.meter import MeterSpec, simple_meter
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.spec import PieceSpec, VoiceSpec
from cadenzra.model.state import PipelineState, voice_key
from cadenzra.model.structure import DynamicsPlan, DynTarget, SectionPlan, StructurePlan
from cadenzra.model.style import RhythmicCell, StylePack
from cadenzra.verification.voice import validate_voice

RESULTS_DIR = Path("docs/harness-results")


@dataclass
class TrialResult:
    """One trial: how many attempts it took, and what went wrong on the way."""

    converged: bool
    attempts: int
    messages: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class HarnessReport:
    """The measurement a prompt change is judged by."""

    capability: str
    variant: str
    model: str
    meter: str
    trials: list[TrialResult]
    seconds: float

    @property
    def pass_rate(self) -> float:
        if not self.trials:
            return 0.0
        return sum(1 for trial in self.trials if trial.converged) / len(self.trials)

    @property
    def first_attempt_rate(self) -> float:
        if not self.trials:
            return 0.0
        return sum(
            1 for trial in self.trials if trial.converged and trial.attempts == 1
        ) / len(self.trials)

    def summary(self) -> str:
        return (
            f"{self.capability} [{self.variant}] {self.meter} on {self.model}: "
            f"{self.pass_rate:.0%} converged within budget, "
            f"{self.first_attempt_rate:.0%} on the first attempt "
            f"({len(self.trials)} trials, {self.seconds:.0f}s)"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "capability": self.capability,
            "variant": self.variant,
            "model": self.model,
            "meter": self.meter,
            "trials": len(self.trials),
            "pass_rate": round(self.pass_rate, 3),
            "first_attempt_rate": round(self.first_attempt_rate, 3),
            "seconds": round(self.seconds, 1),
            "failures": [
                {"attempts": trial.attempts, "messages": trial.messages, "error": trial.error}
                for trial in self.trials
                if not trial.converged
            ],
        }


ALTO = VoiceSpec(
    voice_id="alto",
    kind="vocal",
    range_low=Pitch(step="G", octave=3),
    range_high=Pitch(step="C", octave=5),
    midi_program=52,
)

_CELLS: dict[str, list[RhythmicCell]] = {
    "7/8 (2+2+3)": [
        RhythmicCell(
            meter=simple_meter(7, 8, [2, 2, 3]),
            lily="c8 c c c c4.",
            description="four eighths then a dotted quarter — the 2+2+3 shape",
        ),
        RhythmicCell(
            meter=simple_meter(7, 8, [2, 2, 3]),
            lily="c4 c4 c8 c8 c8",
            description="two quarters then three eighths",
        ),
    ],
    "5/4 (3+2)": [
        RhythmicCell(
            meter=simple_meter(5, 4, [3, 2]),
            lily="c4 c c c c",
            description="five plain quarters",
        ),
        RhythmicCell(
            meter=simple_meter(5, 4, [3, 2]),
            lily="c2. c2",
            description="dotted half plus half — the 3+2 shape",
        ),
    ],
}


def harness_style(meter: MeterSpec, *, with_cells: bool = True) -> StylePack:
    """The style pack a trial runs against.

    `with_cells` is the A/B switch that docs/09 asks for: it measures whether
    showing vetted rhythmic cells actually raises the pass rate in odd meters,
    or whether the prompt's prose about grouping is doing the work.
    """
    return StylePack(
        idioms=["dark modal writing", "stepwise lines with occasional fourths"],
        rhythmic_cells=_CELLS.get(meter.surface_string(), []) if with_cells else [],
        harmony_guidance="modal; avoid leading tones",
    )


def harness_state(meter: MeterSpec, bars: int = 8, *, with_cells: bool = True) -> PipelineState:
    """A minimal one-voice, one-section state for a single-capability trial."""
    section = SectionPlan(
        section_id="A",
        bars=bars,
        meter=meter,
        key="d minor",
        tempo_bpm=96,
        texture="flowing single line",
        dynamics=DynamicsPlan(start="p", targets=[DynTarget(bar=bars, level="f")]),
        active_voices=[ALTO.voice_id],
        intent="a self-contained phrase that breathes",
    )
    return PipelineState(
        spec=PieceSpec(
            title="Harness trial",
            style_prompt="dark modal",
            voices=[ALTO],
            meters_allowed=[meter],
            target_minutes=0.5,
        ),
        style=harness_style(meter, with_cells=with_cells),
        structure=StructurePlan(sections=[section]),
        harmony={"A": _skeleton(meter, bars)},
    )


def _skeleton(meter: MeterSpec, bars: int) -> HarmonicSkeleton:
    """One chord per bar, alternating — enough to write against."""
    chords = ["Dm", "Bb", "C", "Am"]
    return HarmonicSkeleton(
        section_id="A",
        events=[
            HarmonicEvent(
                offset=Fraction(bar) * meter.bar_length,
                duration=meter.bar_length,
                chord=chords[bar % len(chords)],
            )
            for bar in range(bars)
        ],
    )


def run_voice_trials(
    config: RunConfig,
    meter: MeterSpec,
    *,
    trials: int = 10,
    budget: int = 3,
    bars: int = 8,
    with_cells: bool = True,
    workdir: Path,
) -> HarnessReport:
    """Run the generate-validate loop live, `trials` times, and measure it."""
    # Harness runs are logged too: a surface A/B is exactly the case where the
    # verbatim prompts of both arms are the thing worth reading afterwards.
    runlog = open_run_log(config, workdir)
    generator = build_generator(config, runlog)
    renderer = build_renderer(config, runlog)
    started = time.monotonic()

    results = []
    for trial in range(trials):
        results.append(
            _one_trial(
                generator,
                renderer,
                meter,
                bars=bars,
                budget=budget,
                with_cells=with_cells,
                workdir=workdir / f"trial-{trial:02d}",
            )
        )

    return HarnessReport(
        capability="generate_voice",
        variant="cells" if with_cells else "no-cells",
        model=config.generation_model,
        meter=meter.surface_string(),
        trials=results,
        seconds=time.monotonic() - started,
    )


def _one_trial(
    generator: object,
    renderer: object,
    meter: MeterSpec,
    *,
    bars: int,
    budget: int,
    with_cells: bool,
    workdir: Path,
) -> TrialResult:
    """One generate-validate loop, run to convergence or budget exhaustion."""
    state = harness_state(meter, bars, with_cells=with_cells)
    section_id: SectionId = "A"
    voice_id: VoiceId = ALTO.voice_id
    messages: list[str] = []

    for attempt in range(1, budget + 1):
        try:
            ctx = build_voice_context(state, section_id, voice_id)
            part = generator.generate_voice(ctx)  # type: ignore[attr-defined]
        except CadenzraError as error:
            return TrialResult(converged=False, attempts=attempt, error=str(error))

        state = state.model_copy(
            update={"voices": state.voices | {voice_key(section_id, voice_id): part}}
        )
        assert state.structure is not None
        feedback = validate_voice(
            part,
            ALTO,
            state.structure.sections_by_id[section_id],
            renderer,  # type: ignore[arg-type]
            workdir / f"attempt-{attempt}",
        )
        if not feedback:
            return TrialResult(converged=True, attempts=attempt, messages=messages)

        messages += [item.message for item in feedback]
        state = state.model_copy(update={"feedback": feedback})

    return TrialResult(converged=False, attempts=budget, messages=messages)


def record(report: HarnessReport, results_dir: Path = RESULTS_DIR) -> Path:
    """Write a report to the repo so prompt regressions are visible (docs/09)."""
    results_dir.mkdir(parents=True, exist_ok=True)
    slug = (
        f"{report.capability}-{report.variant}-"
        f"{report.meter.split(' ')[0].replace('/', '-')}-{report.model}"
    )
    path = results_dir / f"{slug}.json"
    path.write_text(json.dumps(report.as_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def compare(reports: Sequence[HarnessReport]) -> str:
    """An A/B summary — the form a surface decision is actually made from."""
    lines = ["Surface A/B:"]
    for report in reports:
        lines.append(f"  {report.summary()}")
    if len(reports) == 2:
        delta = reports[0].pass_rate - reports[1].pass_rate
        lines.append(
            f"  difference: {delta:+.0%} in favour of "
            f"{reports[0].variant if delta >= 0 else reports[1].variant}"
        )
    return "\n".join(lines)
