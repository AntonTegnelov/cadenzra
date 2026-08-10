"""One run's accounting, computed from its own flow log.

`llm.jsonl` already records every turn's usage and purpose and every
validation's structured items, so the summary is a single reader over that
file rather than a set of counters threaded through the pipeline. The cost
audit that motivated this took a day of scripted reconstruction; this file is
that script, run at the end of every run, written next to the log it read.
"""

import json
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

from cadenzra.app.config import RunConfig
from cadenzra.model.spec import PieceSpec
from cadenzra.model.state import PipelineState

_USAGE_KEYS = ("input_tokens", "answer_tokens", "thinking_tokens", "cached_tokens")


def git_provenance() -> dict[str, Any]:
    """The commit a run was produced by, and whether the tree was clean.

    Which code produced run X is the single most consequential fact when
    reading its log during active development — the double-fugue autopsy had
    to establish it from commit timestamps. Git is an external system: absent
    or failing, the answer is nulls, never an exception.
    """
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        porcelain = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
        return {"sha": sha, "dirty": bool(porcelain.strip())}
    except (OSError, subprocess.SubprocessError):
        return {"sha": None, "dirty": None}


def write_run_summary(
    *,
    state: PipelineState | None,
    config: RunConfig,
    spec: PieceSpec,
    spec_name: str,
    status: str,
    failure: dict[str, Any] | None,
    run_dir: Path,
    index_path: Path,
) -> dict[str, Any]:
    """Aggregate the run's flow log into `summary.json` and one index line.

    `state` is unused today but part of the signature on purpose: the summary
    is written on the failure path too, where partial state is exactly what a
    future field might need to describe.
    """
    records = _read_flow(run_dir / "llm.jsonl")
    stages = _stage_totals(records)
    totals = _grand_totals(stages)
    totals["dollars"] = _dollars(records, config)

    summary: dict[str, Any] = {
        "run": run_dir.name,
        "spec_name": spec_name,
        "spec": spec.model_dump(mode="json"),
        "git": git_provenance(),
        "config": _config_dump(config),
        "status": status,
        "failure": failure,
        "stages": stages,
        "convergence": _convergence(records),
        "totals": totals,
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    index_line = {
        "run": run_dir.name,
        "spec": spec_name,
        "sha": summary["git"]["sha"],
        "dirty": summary["git"]["dirty"],
        "status": status,
        "turns": totals["turns"],
        **{key: totals[key] for key in _USAGE_KEYS},
        "seconds": totals["seconds"],
        "dollars": totals["dollars"],
    }
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(index_line, ensure_ascii=False) + "\n")

    return summary


def _read_flow(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _stage_totals(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    stages: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "turns": 0,
            **dict.fromkeys(_USAGE_KEYS, 0),
            "seconds": 0.0,
            "retries": 0,
            "regenerations": 0,
        }
    )
    for record in records:
        if record.get("kind") != "llm_turn":
            continue
        stage = stages[str(record.get("label") or record.get("tool") or "?")]
        stage["turns"] += 1
        stage["seconds"] = round(stage["seconds"] + float(record.get("seconds") or 0.0), 3)
        if int(record.get("attempt") or 1) > 1:
            stage["retries"] += 1
        if record.get("purpose") in ("repair", "retry"):
            stage["regenerations"] += 1
        usage = record.get("usage") or {}
        for key in _USAGE_KEYS:
            stage[key] += int(usage.get(key) or 0)
    return dict(stages)


def _grand_totals(stages: dict[str, dict[str, Any]]) -> dict[str, Any]:
    totals: dict[str, Any] = {"turns": 0, **dict.fromkeys(_USAGE_KEYS, 0), "seconds": 0.0}
    for stage in stages.values():
        totals["turns"] += stage["turns"]
        totals["seconds"] = round(totals["seconds"] + stage["seconds"], 3)
        for key in _USAGE_KEYS:
            totals[key] += stage[key]
    return totals


def _dollars(records: list[dict[str, Any]], config: RunConfig) -> float | None:
    """Spend across turns, or None when any model in the run is unpriced.

    Half a bill is worse than no bill: a run mixing a priced and an unpriced
    model would otherwise report a figure that looks complete and is not.
    """
    if not config.prices:
        return None
    total = 0.0
    for record in records:
        if record.get("kind") != "llm_turn":
            continue
        usage = record.get("usage")
        if not usage:
            continue
        price = config.prices.get(str(record.get("model")))
        if price is None:
            return None
        total += price.dollars(
            input_tokens=int(usage.get("input_tokens") or 0),
            answer_tokens=int(usage.get("answer_tokens") or 0),
            thinking_tokens=int(usage.get("thinking_tokens") or 0),
        )
    return round(total, 4)


def _convergence(records: list[dict[str, Any]]) -> dict[str, list[dict[str, int]]]:
    """Per loop, the raw and deduplicated violation count per attempt.

    "263 → 63 → 66" should be one line to read; this is that line. Distinct
    counts come from the structured item ids; validations recorded without
    items fall back to the raw count.
    """
    loops: dict[str, list[dict[str, int]]] = defaultdict(list)
    for record in records:
        if record.get("kind") != "validation":
            continue
        messages = record.get("messages") or []
        items = record.get("items")
        distinct = (
            len({str(item.get("id")) for item in items})
            if items
            else len(messages)
        )
        loops[str(record.get("loop_key"))].append(
            {
                "attempt": int(record.get("attempt") or 0),
                "raw": len(messages),
                "distinct": distinct,
            }
        )
    return dict(loops)


def _config_dump(config: RunConfig) -> dict[str, Any]:
    dumped = config.model_dump(mode="json")
    dumped.pop("gemini_key", None)
    return dumped
