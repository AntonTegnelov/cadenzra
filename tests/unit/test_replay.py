"""Replay: one logged turn, re-fired for the price of one call.

Most re-runs in the cost audit existed to test a prompt fix — a forty-minute,
full-price piece to evaluate one changed turn. The log stores every prompt
verbatim but not the tool schema, so a registry rebuilds the schema from the
tool's name; anything it cannot rebuild truthfully is a loud error naming
what is missing.
"""

import json
from pathlib import Path

import pytest

from cadenzra.app.replay import replay_record
from cadenzra.app.specs import SPECS
from cadenzra.common.errors import CadenzraError
from cadenzra.llm.schemas.registry import REPLAYABLE_TOOLS, schema_for

SPEC = SPECS["tool-choir"]  # has singing voices, so every schema is reachable


def test_every_generator_tool_can_rebuild_its_schema() -> None:
    """The registry must cover every tool the generator can emit — a turn that
    cannot be replayed silently would rot the moment a capability is added."""
    from cadenzra.llm.schemas.lyrics import (
        OBSERVE_DEVICES_TOOL,
        PLAN_LYRICS_TOOL,
        WRITE_LYRICS_TOOL,
    )
    from cadenzra.llm.schemas.structured import (
        DERIVE_STYLE_TOOL,
        PLAN_STRUCTURE_TOOL,
        REVIEW_TOOL,
        WRITE_HARMONY_TOOL,
        WRITE_MOTIFS_TOOL,
    )
    from cadenzra.llm.schemas.voice import WRITE_PART_TOOL

    generator_tools = {
        DERIVE_STYLE_TOOL,
        PLAN_STRUCTURE_TOOL,
        WRITE_MOTIFS_TOOL,
        WRITE_HARMONY_TOOL,
        WRITE_PART_TOOL,
        PLAN_LYRICS_TOOL,
        WRITE_LYRICS_TOOL,
        OBSERVE_DEVICES_TOOL,
        REVIEW_TOOL,
    }
    assert generator_tools <= REPLAYABLE_TOOLS


def test_spec_only_schemas_need_no_state() -> None:
    for tool in ("describe_style", "plan_structure", "write_motifs", "write_part"):
        schema = schema_for(tool, spec=SPEC, state=None, section_id=None)
        assert schema["name"] == tool


def test_state_dependent_schemas_fail_loudly_without_their_slice() -> None:
    with pytest.raises(CadenzraError, match="structure"):
        schema_for("write_harmony", spec=SPEC, state=None, section_id="A")


def test_an_unknown_tool_is_a_loud_error() -> None:
    with pytest.raises(CadenzraError, match="no_such_tool"):
        schema_for("no_such_tool", spec=SPEC, state=None, section_id=None)


def test_the_record_loader_finds_a_turn_by_seq(tmp_path: Path) -> None:
    flow = tmp_path / "llm.jsonl"
    flow.write_text(
        "\n".join(
            json.dumps(record)
            for record in [
                {"kind": "note", "heading": "h", "text": "t"},
                {"kind": "llm_turn", "seq": 1, "tool": "write_part", "user_prompt": "u"},
                {"kind": "llm_turn", "seq": 2, "tool": "write_harmony", "user_prompt": "v"},
            ]
        )
    )

    record = replay_record(flow, 2)

    assert record["tool"] == "write_harmony"


def test_a_missing_seq_reports_the_available_range(tmp_path: Path) -> None:
    flow = tmp_path / "llm.jsonl"
    flow.write_text(
        json.dumps({"kind": "llm_turn", "seq": 1, "tool": "write_part"}) + "\n"
    )

    with pytest.raises(CadenzraError, match="1..1"):
        replay_record(flow, 9)


def test_a_missing_log_is_a_loud_error(tmp_path: Path) -> None:
    with pytest.raises(CadenzraError, match="llm.jsonl"):
        replay_record(tmp_path / "llm.jsonl", 1)
