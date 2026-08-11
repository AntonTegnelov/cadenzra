"""The offline audit: stored states and logs, current validators, no API.

The corpus is the cheapest test material the project owns — 130+ real runs.
These pin the two instruments: the frequency ledger (the measured common-vs-
rare split behind the surface design principle) and the validator replay
over stored states.
"""

import json
from pathlib import Path

from cadenzra.app.audit import audit_states, frequency_ledger, run_audit
from cadenzra.model.primitives.meter import simple_meter
from cadenzra.model.primitives.pitch import Pitch
from cadenzra.model.spec import PieceSpec, VoiceSpec
from cadenzra.model.state import PipelineState
from cadenzra.model.structure import DynamicsPlan, SectionPlan, StructurePlan
from cadenzra.model.style import StylePack
from tests.fakes.renderer import RecordingRenderer

SEVEN_EIGHT = simple_meter(7, 8, [2, 2, 3])
FOUR_FOUR = simple_meter(4, 4)


def _state() -> PipelineState:
    """A state carrying two deliberate faults for the current validators:
    an incoherent style pack, and a section meter outside the palette."""
    alto = VoiceSpec(
        voice_id="alto",
        kind="vocal",
        range_low=Pitch(step="G", octave=3),
        range_high=Pitch(step="C", octave=5),
        midi_program=52,
    )
    spec = PieceSpec(
        title="T",
        style_prompt="s",
        voices=[alto],
        meters_allowed=[SEVEN_EIGHT],
        target_minutes=1.0,
    )
    return PipelineState(
        spec=spec,
        style=StylePack(
            idioms=["doubling of melody in octaves"],
            parallel_fifths_policy="forbid",
        ),
        structure=StructurePlan(
            sections=[
                SectionPlan(
                    section_id="A",
                    bars=8,
                    meter=FOUR_FOUR,
                    key="c major",
                    tempo_bpm=90,
                    texture="homophonic",
                    dynamics=DynamicsPlan(start="mf"),
                    active_voices=["alto"],
                )
            ]
        ),
    )


def _corpus(tmp_path: Path) -> Path:
    out = tmp_path / "out"
    run = out / "probe" / "runs" / "20260101-000000"
    run.mkdir(parents=True)
    (run / "state.json").write_text(_state().model_dump_json(), encoding="utf-8")
    records = [
        {
            "kind": "validation",
            "loop_key": "voice:A:alto",
            "attempt": 1,
            "items": [{"kind": "range", "message": "too low"}],
        },
        {
            "kind": "validation",
            "loop_key": "voice:A:alto",
            "attempt": 2,
            "items": [{"kind": "range", "message": "still too low"}],
        },
        {
            "kind": "validation",
            "loop_key": "harmony:A",
            "attempt": 1,
            "messages": ["an old-format record with no structured items"],
        },
        {"kind": "llm_turn", "seq": 1},
    ]
    (run / "llm.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records), encoding="utf-8"
    )
    return out


def test_the_ledger_measures_kinds_by_layer(tmp_path: Path) -> None:
    ledger = frequency_ledger(_corpus(tmp_path))

    assert ledger[("voice", "range")] == 2
    assert ledger[("harmony", "unstructured")] == 1


def test_stored_states_replay_through_the_current_validators(
    tmp_path: Path,
) -> None:
    findings = audit_states(_corpus(tmp_path), RecordingRenderer(), tmp_path / "w")

    layers = {finding.layer for finding in findings}
    assert "style" in layers, "the incoherent pack is caught"
    assert "structure" in layers, "the out-of-palette meter is caught"
    assert all(finding.spec == "probe" for finding in findings)
    assert all(finding.run == "20260101-000000" for finding in findings)


def test_the_report_summarizes_and_dumps_json(tmp_path: Path) -> None:
    out = _corpus(tmp_path)
    json_path = tmp_path / "report.json"

    report = run_audit(
        out, RecordingRenderer(), tmp_path / "w", json_path=json_path
    )

    assert "voice" in report and "range" in report
    dumped = json.loads(json_path.read_text(encoding="utf-8"))
    assert dumped["ledger"][0]["count"] == 2
    assert any(f["layer"] == "style" for f in dumped["findings"])
