"""Re-fire one logged LLM turn, for the price of one call.

During the quality deep-dive, evaluating a prompt or schema change meant
re-running a whole piece — forty minutes and full price to see one turn
differently. Replay fires the *logged* prompt against the *current* schema and
model wiring, records the result into a fresh run dir, and prints what came
back. It does not rebuild the prompt: what was said is history; what changed
is the code around it.
"""

import json
import logging
from pathlib import Path
from typing import Any

from cadenzra.app.config import RunConfig
from cadenzra.common.errors import CadenzraError
from cadenzra.common.runlog import RunLog, TurnInfo, run_stamp
from cadenzra.llm.schemas.registry import schema_for
from cadenzra.model.spec import PieceSpec
from cadenzra.model.state import PipelineState

_log = logging.getLogger(__name__)


def replay_record(flow_path: Path, seq: int) -> dict[str, Any]:
    """The logged llm_turn with this seq, or a loud error naming the range."""
    if not flow_path.exists():
        raise CadenzraError(f"no flow log at {flow_path}")
    turns: dict[int, dict[str, Any]] = {}
    for line in flow_path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        record = json.loads(line)
        if record.get("kind") == "llm_turn":
            turns[int(record["seq"])] = record
    if seq in turns:
        return turns[seq]
    if not turns:
        raise CadenzraError(f"{flow_path} holds no llm_turn records")
    raise CadenzraError(
        f"no turn {seq} in {flow_path}; the log holds seq "
        f"{min(turns)}..{max(turns)}"
    )


def run_replay(
    config: RunConfig, spec: PieceSpec, spec_name: str, run: str, seq: int
) -> int:
    """Fire one logged turn again and print what the model says now."""
    from cadenzra.app.factory import build_client_for_tool

    out = config.output_dir / spec_name
    run_dir = out / "runs" / run
    record = replay_record(run_dir / "llm.jsonl", seq)
    tool_name = str(record["tool"])
    state = _saved_state(run_dir, out)

    schema = schema_for(
        tool_name, spec=spec, state=state, section_id=record.get("section")
    )
    replay_log = RunLog(
        out / "runs" / f"{run_stamp()}-replay", technical_level=config.log_level
    )
    client = build_client_for_tool(config, tool_name, replay_log)
    try:
        arguments = client.call_tool(
            system_prompt=str(record["system_prompt"]),
            user_prompt=str(record["user_prompt"]),
            tool=schema,
            turn=TurnInfo(
                label=tool_name,
                section_id=record.get("section"),
                voice_id=record.get("voice"),
                purpose="replay",
            ),
        )
    finally:
        replay_log.close()

    print(f"replayed turn {seq} ({tool_name}) from {run}")
    print(f"the replay's own log is at {replay_log.dir}")
    print(json.dumps(arguments, indent=2, ensure_ascii=False))
    return 0


def _saved_state(run_dir: Path, out: Path) -> PipelineState | None:
    """The run's own state copy, falling back to the spec-level one.

    Older runs predate the per-run copy; the spec-level file may have been
    overwritten by a later run, which the state-dependent schema builders
    tolerate only as far as the slices they read still describe this run.
    """
    for candidate in (run_dir / "state.json", out / "state.json"):
        if candidate.exists():
            return PipelineState.model_validate_json(
                candidate.read_text(encoding="utf-8")
            )
    return None
