"""The decidable half of judging a performance.

This check exists because the LLM half turned out not to be trustworthy for
this particular question — see the module docstring in `verification/audio.py`
and the finding recorded in `docs/harness-results/`.
"""

from pathlib import Path

import mido
import pytest

from cadenzra.model.primitives.meter import simple_meter
from cadenzra.model.structure import DynamicsPlan, DynTarget, SectionPlan, StructurePlan
from cadenzra.performance.curves import EXPRESSION_CONTROLLER
from cadenzra.verification.audio import planned_spread, validate_audio_dynamics

FOUR_FOUR = simple_meter(4, 4)


def _plan(start: str, target: str | None) -> StructurePlan:
    return StructurePlan(
        sections=[
            SectionPlan(
                section_id="A",
                bars=4,
                meter=FOUR_FOUR,
                key="c major",
                tempo_bpm=90,
                texture="homophonic",
                dynamics=DynamicsPlan(
                    start=start,
                    targets=[DynTarget(bar=4, level=target)] if target else [],
                ),
                active_voices=["soprano"],
            )
        ]
    )


def _performance(path: Path, values: list[int]) -> Path:
    midi = mido.MidiFile(ticks_per_beat=384)
    track = mido.MidiTrack()
    track.name = "staff:soprano"
    midi.tracks.append(track)
    for value in values:
        track.append(
            mido.Message(
                "control_change",
                channel=0,
                control=EXPRESSION_CONTROLLER,
                value=value,
                time=96,
            )
        )
    track.append(mido.Message("note_on", channel=0, note=60, velocity=90, time=0))
    track.append(mido.Message("note_off", channel=0, note=60, velocity=0, time=384))
    midi.save(path)
    return path


def _audio(path: Path, *, amplitude: int) -> Path:
    import wave
    from array import array

    samples = array("h", [amplitude] * 44100)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(44100)
        handle.writeframes(samples.tobytes())
    return path


def test_a_planned_arc_carried_by_the_performance_passes(tmp_path: Path) -> None:
    audio = _audio(tmp_path / "a.wav", amplitude=8000)
    performance = _performance(tmp_path / "a.mid", [28, 50, 80, 112])

    assert validate_audio_dynamics(audio, performance, _plan("pp", "ff")) == []


def test_a_planned_arc_the_performance_dropped_is_caught(tmp_path: Path) -> None:
    """The failure this check exists for: the plan asks for a swell and the
    interpretation stage produced a flat line."""
    audio = _audio(tmp_path / "a.wav", amplitude=8000)
    performance = _performance(tmp_path / "a.mid", [78, 78, 78])

    feedback = validate_audio_dynamics(audio, performance, _plan("pp", "ff"))

    assert len(feedback) == 1
    assert feedback[0].level == "interpretation"
    assert "carries almost none of it" in feedback[0].message


def test_a_performance_with_no_expression_at_all_is_caught(tmp_path: Path) -> None:
    audio = _audio(tmp_path / "a.wav", amplitude=8000)
    performance = _performance(tmp_path / "a.mid", [])

    assert validate_audio_dynamics(audio, performance, _plan("pp", "ff"))


def test_a_flat_plan_is_not_asked_to_have_an_arc(tmp_path: Path) -> None:
    """Nothing to check when the music never asked to move."""
    audio = _audio(tmp_path / "a.wav", amplitude=8000)
    performance = _performance(tmp_path / "a.mid", [78])

    assert validate_audio_dynamics(audio, performance, _plan("mf", None)) == []


def test_a_reduced_but_real_arc_is_accepted(tmp_path: Path) -> None:
    """A style that dials expression down is making a choice, not failing."""
    audio = _audio(tmp_path / "a.wav", amplitude=8000)
    performance = _performance(tmp_path / "a.mid", [60, 70, 80, 95])

    assert validate_audio_dynamics(audio, performance, _plan("pp", "ff")) == []


def test_silent_audio_is_caught(tmp_path: Path) -> None:
    audio = _audio(tmp_path / "a.wav", amplitude=0)
    performance = _performance(tmp_path / "a.mid", [28, 112])

    feedback = validate_audio_dynamics(audio, performance, _plan("pp", "ff"))

    assert any("silent" in item.message for item in feedback)


@pytest.mark.parametrize(
    ("start", "target", "expected"),
    [("pp", "ff", 84), ("mf", None, 0), ("ppp", "fff", 111)],
)
def test_the_planned_spread_is_read_from_the_plan(
    start: str, target: str | None, expected: int
) -> None:
    assert planned_spread(_plan(start, target)) == expected
