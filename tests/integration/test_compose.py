"""The M4 gate: a whole piece, real tools, no LLM.

A `ScriptedGenerator` supplies the music so the test is deterministic, but
everything below it is real — LilyPond compiles the score, FluidSynth renders
the audio. What is asserted is the promise from docs/01: the artifacts are
mutually consistent because they derive from one canonical text, and the
crescendo the plan asked for is audible rather than merely printed.
"""

import math
import wave
from array import array
from fractions import Fraction
from pathlib import Path

import mido
import pytest

from cadenzra.app.compose import ComposeServices, compose
from cadenzra.app.config import RetryBudgets
from cadenzra.model.artifacts import RenderedArtifacts
from cadenzra.model.harmony import HarmonicEvent, HarmonicSkeleton
from cadenzra.model.primitives.meter import simple_meter
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.spec import PieceSpec, VoiceSpec
from cadenzra.model.state import PipelineState
from cadenzra.model.structure import DynamicsPlan, DynTarget, SectionPlan, StructurePlan
from cadenzra.model.style import StylePack
from cadenzra.performance.curves import EXPRESSION_CONTROLLER
from cadenzra.rendering.fluidsynth import FluidsynthAdapter
from cadenzra.rendering.lilypond import LilypondAdapter
from cadenzra.verification.midi_analysis import (
    channel_track_invariant_ok,
    extract_voice_notes,
)
from tests.fakes.generator import ScriptedGenerator

pytestmark = pytest.mark.integration

FIVE_FOUR = simple_meter(5, 4, [3, 2])
SEVEN_EIGHT = simple_meter(7, 8, [2, 2, 3])

SOPRANO = VoiceSpec(
    voice_id="soprano",
    kind="vocal",
    range_low=Pitch(step="C", octave=4),
    range_high=Pitch(step="G", octave=5),
    midi_program=52,
)
ALTO = VoiceSpec(
    voice_id="alto",
    kind="vocal",
    range_low=Pitch(step="G", octave=3),
    range_high=Pitch(step="C", octave=5),
    midi_program=52,
)

SPEC = PieceSpec(
    title="Smoke",
    style_prompt="dark modal duet",
    voices=[SOPRANO, ALTO],
    meters_allowed=[FIVE_FOUR, SEVEN_EIGHT],
    # Two bars of 5/4 plus two of 7/8 at 92bpm is about 0.19 minutes; the spec
    # has to ask for what the fixed plan below actually is, or the structure
    # validator rejects it — correctly.
    target_minutes=0.19,
    tempo_bpm=92,
)

# Two sections, two voices, 5/4 and 7/8, and a held note that swells from
# nothing to full — the smallest piece that exercises every seam, including
# the score/performance split (docs/09).
SECTIONS = [
    SectionPlan(
        section_id="A",
        bars=2,
        meter=FIVE_FOUR,
        key="d minor",
        tempo_bpm=92,
        texture="homophonic",
        dynamics=DynamicsPlan(start="pp", targets=[DynTarget(bar=2, level="ff")]),
        active_voices=["soprano", "alto"],
    ),
    SectionPlan(
        section_id="B",
        bars=2,
        meter=SEVEN_EIGHT,
        key="d minor",
        tempo_bpm=92,
        texture="homophonic",
        dynamics=DynamicsPlan(start="ff", targets=[DynTarget(bar=2, level="pp")]),
        active_voices=["soprano", "alto"],
    ),
]

PLAN = StructurePlan(sections=SECTIONS, form_summary="a swell and a fade")

# One long held note per bar in the first section, so the crescendo has
# something to happen on; a shorter figure in the second. Section B is 7/8, so
# each of its bars holds seven eighths: 3 + 2 + 2.
FRAGMENTS = {
    ("A", "soprano"): "d''1 ~ d''4 |\na'1 ~ a'4 |",
    ("A", "alto"): "a'1 ~ a'4 |\nf'1 ~ f'4 |",
    ("B", "soprano"): "d''4. d''4 d''4 |\na'4. a'4 a'4 |",
    ("B", "alto"): "a'4. a'4 a'4 |\nf'4. f'4 f'4 |",
}


def _skeletons() -> dict[str, HarmonicSkeleton]:
    return {
        "A": HarmonicSkeleton(
            section_id="A",
            events=[
                HarmonicEvent(offset=Fraction(0), duration=Fraction(5, 4), chord="Dm"),
                HarmonicEvent(offset=Fraction(5, 4), duration=Fraction(5, 4), chord="Dm"),
            ],
        ),
        "B": HarmonicSkeleton(
            section_id="B",
            events=[
                HarmonicEvent(offset=Fraction(0), duration=Fraction(7, 8), chord="Dm"),
                HarmonicEvent(offset=Fraction(7, 8), duration=Fraction(7, 8), chord="Dm"),
            ],
        ),
    }


@pytest.fixture(scope="module")
def composed(tmp_path_factory: pytest.TempPathFactory) -> tuple[PipelineState, Path]:
    """Compose the smoke piece once; the assertions below all read it."""
    out = tmp_path_factory.mktemp("compose")
    generator = ScriptedGenerator(
        by_voice=FRAGMENTS,
        style=StylePack(parallel_fifths_policy="allow"),
        plans=[PLAN],
        skeletons=list(_skeletons().values()),
    )
    services = ComposeServices(
        generator=generator,
        renderer=LilypondAdapter(),
        workdir=out / "work",
        budgets=RetryBudgets(),
        synthesizer=FluidsynthAdapter(),
        output_dir=out,
    )
    return compose(SPEC, services), out


def _artifacts(composed: tuple[PipelineState, Path]) -> RenderedArtifacts:
    """The run's artifacts. Absent means the run did not finish, which is a
    test failure rather than a case to handle."""
    state, _ = composed
    assert state.artifacts is not None
    return state.artifacts


def test_a_run_emits_all_five_artifacts(
    composed: tuple[PipelineState, Path],
) -> None:
    artifacts = _artifacts(composed)

    for path in (
        artifacts.lily_path,
        artifacts.pdf_path,
        artifacts.score_midi_path,
        artifacts.performance_midi_path,
        artifacts.audio_path,
    ):
        assert path.exists() and path.stat().st_size > 0, path


def test_the_score_holds_every_section_and_voice(
    composed: tuple[PipelineState, Path],
) -> None:
    source = _artifacts(composed).lily_path.read_text(encoding="utf-8")

    assert "\\time #'(3 2) 5/4" in source
    assert "\\time #'(2 2 3) 7/8" in source
    assert '\\new Voice = "soprano"' in source
    assert '\\new Voice = "alto"' in source


def test_the_compiled_score_keeps_one_voice_to_a_channel(
    composed: tuple[PipelineState, Path],
) -> None:
    """Every analysis validator and every per-voice performance mechanism
    depends on this holding all the way through assembly (docs/03)."""
    score_midi = mido.MidiFile(_artifacts(composed).score_midi_path)

    assert channel_track_invariant_ok(score_midi)
    assert set(extract_voice_notes(score_midi)) == {"soprano", "alto"}


def test_the_performance_says_the_same_notes_as_the_score(
    composed: tuple[PipelineState, Path],
) -> None:
    """Interpretation shapes a performance; it never rewrites the music."""
    artifacts = _artifacts(composed)

    assert _notes(mido.MidiFile(artifacts.performance_midi_path)) == _notes(
        mido.MidiFile(artifacts.score_midi_path)
    )


def test_the_performance_adds_the_expression_the_score_lacks(
    composed: tuple[PipelineState, Path],
) -> None:
    artifacts = _artifacts(composed)

    score_cc = _expression(mido.MidiFile(artifacts.score_midi_path))
    performance_cc = _expression(mido.MidiFile(artifacts.performance_midi_path))

    assert not score_cc
    assert len(performance_cc) > 20
    assert max(performance_cc) - min(performance_cc) > 60


def test_the_crescendo_is_audible_not_merely_printed(
    composed: tuple[PipelineState, Path],
) -> None:
    """The reason the score/performance split exists (docs/02). The plan asks
    section A to swell pp to ff and section B to fade ff back to pp; both have
    to move the actual waveform, or the split has bought nothing.

    The threshold is deliberately modest. This piece retriggers its notes each
    bar, so the audible range is narrower than a single held chord's would be —
    what is being proved here is that the curve reaches the audio at all, not
    how dramatic any particular passage sounds.
    """
    envelope = _rms_envelope(_artifacts(composed).audio_path, slices=16)
    swell = envelope[: len(envelope) // 2]
    fade = envelope[len(envelope) // 2 :]

    assert max(swell) > envelope[0] * 3, envelope
    assert max(fade) > min(fade) * 3, envelope
    assert max(swell) > max(fade), envelope


def test_the_audio_lasts_about_as_long_as_the_score(
    composed: tuple[PipelineState, Path],
) -> None:
    artifacts = _artifacts(composed)
    expected = mido.MidiFile(artifacts.score_midi_path).length

    with wave.open(str(artifacts.audio_path)) as handle:
        seconds = handle.getnframes() / handle.getframerate()

    assert expected * 0.8 <= seconds <= expected * 1.5 + 3


def test_the_run_writes_its_state_for_debugging(
    composed: tuple[PipelineState, Path],
) -> None:
    """A complete record of the run, readable back (docs/07)."""
    _, out = composed

    assert (out / "state.json").exists()
    assert (out / "score.ly").exists()


def _notes(midi: mido.MidiFile) -> list[tuple[int, int]]:
    return [
        (message.note, message.channel)
        for track in midi.tracks
        for message in track
        if message.type == "note_on" and message.velocity > 0
    ]


def _expression(midi: mido.MidiFile) -> list[int]:
    return [
        message.value
        for track in midi.tracks
        for message in track
        if message.type == "control_change" and message.control == EXPRESSION_CONTROLLER
    ]


def _rms_envelope(path: Path, *, slices: int) -> list[float]:
    with wave.open(str(path)) as handle:
        channels = handle.getnchannels()
        samples = array("h")
        samples.frombytes(handle.readframes(handle.getnframes()))
    mono = samples[0::channels]
    width = max(1, len(mono) // slices)
    return [
        math.sqrt(
            sum(float(s) * s for s in mono[index * width : (index + 1) * width])
            / width
        )
        for index in range(slices)
    ]
