"""`summary.json` — a run's accounting, computed from its own flow log.

The log is already the ledger: every turn carries its usage and purpose, every
validation its structured items. The summary is one reader over that file, so
there is no counter threaded through the pipeline to drift out of sync.
"""

import json
from pathlib import Path

from cadenzra.app.config import ModelPrice, RunConfig
from cadenzra.app.specs import SPECS
from cadenzra.app.summary import git_provenance, write_run_summary

SPEC = SPECS["smoke"]


def _config(**overrides: object) -> RunConfig:
    """A config with a throwaway key; `model_validate` keeps mypy off the alias."""
    return RunConfig.model_validate({"GEMINI_KEY": "k", **overrides})


def _turn(
    seq: int,
    label: str,
    *,
    purpose: str = "first",
    attempt: int = 1,
    usage: dict[str, int] | None = None,
    seconds: float = 1.0,
    model: str = "gemini-3.6-flash",
) -> dict[str, object]:
    return {
        "seq": seq,
        "kind": "llm_turn",
        "label": label,
        "purpose": purpose,
        "attempt": attempt,
        "model": model,
        "seconds": seconds,
        "usage": usage,
    }


def _write_flow(run_dir: Path, records: list[dict[str, object]]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "llm.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n"
    )


def _usage(n: int) -> dict[str, int]:
    return {
        "input_tokens": n,
        "answer_tokens": 10,
        "thinking_tokens": 20,
        "cached_tokens": 0,
        "total_tokens": n + 30,
    }


def test_stage_totals_come_from_the_flow_log(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "20260810-120000"
    _write_flow(
        run_dir,
        [
            _turn(1, "write_part", usage=_usage(700)),
            _turn(2, "write_part", purpose="repair", usage=_usage(900), seconds=3.0),
            _turn(3, "write_part", attempt=2, usage=None),
            _turn(4, "plan_structure", usage=_usage(300)),
        ],
    )

    summary = write_run_summary(
        state=None,
        config=_config(),
        spec=SPEC,
        spec_name="smoke",
        status="completed",
        failure=None,
        run_dir=run_dir,
        index_path=tmp_path / "index.jsonl",
    )

    parts = summary["stages"]["write_part"]
    assert parts["turns"] == 3
    assert parts["input_tokens"] == 1600, "turns without usage count zero, not crash"
    assert parts["thinking_tokens"] == 40
    assert parts["retries"] == 1, "attempt > 1 is a retry"
    assert parts["regenerations"] == 1, "purpose repair/retry is a regeneration"
    assert parts["seconds"] == 5.0
    assert summary["stages"]["plan_structure"]["turns"] == 1
    assert summary["totals"]["input_tokens"] == 1900
    assert summary["spec_name"] == "smoke"
    assert summary["status"] == "completed"
    assert (run_dir / "summary.json").exists()


def test_convergence_trajectories_are_read_off_validations(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r"
    items_a = [{"id": "aaaa", "message": "m"}, {"id": "bbbb", "message": "m"}]
    items_b = [{"id": "aaaa", "message": "m"}]
    _write_flow(
        run_dir,
        [
            {
                "kind": "validation",
                "loop_key": "section",
                "attempt": 1,
                "messages": ["m", "m", "m"],
                "items": items_a,
            },
            {
                "kind": "validation",
                "loop_key": "section",
                "attempt": 2,
                "messages": ["m"],
                "items": items_b,
            },
        ],
    )

    summary = write_run_summary(
        state=None,
        config=_config(),
        spec=SPEC,
        spec_name="smoke",
        status="budget_exhausted",
        failure={"loop_key": "section", "message": "stalled"},
        run_dir=run_dir,
        index_path=tmp_path / "index.jsonl",
    )

    assert summary["convergence"]["section"] == [
        {"attempt": 1, "raw": 3, "distinct": 2},
        {"attempt": 2, "raw": 1, "distinct": 1},
    ]
    assert summary["failure"] == {"loop_key": "section", "message": "stalled"}


def test_dollars_are_computed_only_when_the_model_is_priced(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r"
    _write_flow(run_dir, [_turn(1, "write_part", usage=_usage(1_000_000))])

    unpriced = write_run_summary(
        state=None,
        config=_config(),
        spec=SPEC,
        spec_name="smoke",
        status="completed",
        failure=None,
        run_dir=run_dir,
        index_path=tmp_path / "index.jsonl",
    )
    assert unpriced["totals"]["dollars"] is None, "no price table, no guess"

    priced = write_run_summary(
        state=None,
        config=_config(
            prices={
                "gemini-3.6-flash": ModelPrice(
                    input_per_mtok=0.30, output_per_mtok=2.50
                )
            }
        ),
        spec=SPEC,
        spec_name="smoke",
        status="completed",
        failure=None,
        run_dir=run_dir,
        index_path=tmp_path / "index2.jsonl",
    )
    # 1M input at 0.30 + (10 answer + 20 thinking) at 2.50/M
    assert priced["totals"]["dollars"] == round(0.30 + 30 * 2.50 / 1_000_000, 4)


def test_the_key_never_reaches_the_summary(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r"
    _write_flow(run_dir, [_turn(1, "write_part")])

    summary = write_run_summary(
        state=None,
        config=_config(GEMINI_KEY="SECRET"),
        spec=SPEC,
        spec_name="smoke",
        status="completed",
        failure=None,
        run_dir=run_dir,
        index_path=tmp_path / "index.jsonl",
    )

    assert "SECRET" not in json.dumps(summary)
    assert "SECRET" not in (run_dir / "summary.json").read_text()


def test_every_run_appends_one_index_line(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "20260810-120000"
    _write_flow(run_dir, [_turn(1, "write_part", usage=_usage(700))])
    index = tmp_path / "index.jsonl"

    write_run_summary(
        state=None,
        config=_config(),
        spec=SPEC,
        spec_name="smoke",
        status="completed",
        failure=None,
        run_dir=run_dir,
        index_path=index,
    )
    write_run_summary(
        state=None,
        config=_config(),
        spec=SPEC,
        spec_name="smoke",
        status="failed",
        failure={"loop_key": None, "message": "boom"},
        run_dir=run_dir,
        index_path=index,
    )

    lines = [json.loads(line) for line in index.read_text().splitlines()]
    assert len(lines) == 2
    assert lines[0]["spec"] == "smoke"
    assert lines[0]["run"] == "20260810-120000"
    assert lines[0]["input_tokens"] == 700
    assert lines[1]["status"] == "failed"


def test_a_failing_run_still_writes_its_summary_and_both_state_copies(
    tmp_path: Path,
) -> None:
    """The run that died is the one whose accounting matters most — and the
    spec-level state.json is clobbered by re-runs, so the run dir keeps its
    own copy for forensics."""
    import pytest

    from cadenzra.app.compose import ComposeServices, compose
    from cadenzra.common.errors import BudgetExhaustedError, LLMOutputError
    from cadenzra.common.runlog import RunLog
    from tests.fakes.renderer import RecordingRenderer

    class _Failing:
        def derive_style_pack(self, spec: object) -> object:
            raise LLMOutputError("no style at all")

    out = tmp_path / "smoke"
    runlog = RunLog(out / "runs" / "20260810-130000")
    services = ComposeServices(
        generator=_Failing(),  # type: ignore[arg-type]
        renderer=RecordingRenderer(),
        workdir=out / "work",
        budgets=_config().budgets,
        runlog=runlog,
        synthesizer=None,  # type: ignore[arg-type]
        output_dir=out,
        run_config=_config(output_dir=str(tmp_path)),
        spec_name="smoke",
    )

    with pytest.raises(BudgetExhaustedError):
        compose(SPEC, services)
    runlog.close()

    assert (out / "state.json").exists()
    assert (runlog.dir / "state.json").exists(), "the forensic copy"
    summary = json.loads((runlog.dir / "summary.json").read_text())
    assert summary["status"] == "budget_exhausted"
    assert summary["failure"]["loop_key"] == "structure"
    index_lines = (tmp_path / "index.jsonl").read_text().splitlines()
    assert len(index_lines) == 1


def test_git_provenance_reports_or_stays_silent() -> None:
    """In this repo it reports; where git is absent it must return nulls, not
    raise — version control is an external system, not our invariant."""
    provenance = git_provenance()

    assert set(provenance) == {"sha", "dirty"}
    if provenance["sha"] is not None:
        assert isinstance(provenance["sha"], str) and len(provenance["sha"]) >= 7
        assert isinstance(provenance["dirty"], bool)
