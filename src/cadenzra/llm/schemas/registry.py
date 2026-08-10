"""Rebuild a tool schema from its name, for replaying a logged turn.

The flow log stores every prompt verbatim but not the schema dict that forced
the tool call — schemas are cheap to rebuild and expensive to store on every
turn. Spec-shaped schemas rebuild from the spec exactly as the generator
builds them; state-shaped ones read the run's saved state and refuse loudly,
naming the missing slice, rather than guessing an argument.
"""

from typing import Any, Final

from cadenzra.common.errors import CadenzraError
from cadenzra.llm.schemas.lyrics import (
    OBSERVE_DEVICES_TOOL,
    PLAN_LYRICS_TOOL,
    WRITE_LYRICS_TOOL,
    observe_devices_schema,
    plan_lyrics_schema,
    write_lyrics_schema,
)
from cadenzra.llm.schemas.patch import REWRITE_BARS_TOOL, rewrite_bars_schema
from cadenzra.llm.schemas.structured import (
    DERIVE_STYLE_TOOL,
    PLAN_STRUCTURE_TOOL,
    REVIEW_TOOL,
    WRITE_HARMONY_TOOL,
    WRITE_MOTIFS_TOOL,
    describe_style_schema,
    plan_structure_schema,
    review_schema,
    write_harmony_schema,
    write_motifs_schema,
)
from cadenzra.llm.schemas.voice import WRITE_PART_TOOL, write_part_schema
from cadenzra.model.lyrics import RELATIONSHIP_DEFINITIONS
from cadenzra.model.spec import PieceSpec
from cadenzra.model.state import PipelineState

REPLAYABLE_TOOLS: Final = frozenset(
    {
        DERIVE_STYLE_TOOL,
        PLAN_STRUCTURE_TOOL,
        WRITE_MOTIFS_TOOL,
        WRITE_HARMONY_TOOL,
        WRITE_PART_TOOL,
        PLAN_LYRICS_TOOL,
        WRITE_LYRICS_TOOL,
        OBSERVE_DEVICES_TOOL,
        REVIEW_TOOL,
        REWRITE_BARS_TOOL,
    }
)


def schema_for(
    tool: str,
    *,
    spec: PieceSpec,
    state: PipelineState | None,
    section_id: str | None,
) -> dict[str, Any]:
    """The schema the named tool would be called with today.

    "Today" is deliberate: replay fires the *logged* prompt against the
    *current* schema, which is exactly what evaluating a code change on one
    turn means.
    """
    meters = [meter.surface_string() for meter in spec.meters_allowed]
    if tool == DERIVE_STYLE_TOOL:
        return describe_style_schema(meters)
    if tool == PLAN_STRUCTURE_TOOL:
        return plan_structure_schema(
            meters,
            [voice.voice_id for voice in spec.voices],
            sorted(spec.groups),
        )
    if tool == WRITE_MOTIFS_TOOL:
        return write_motifs_schema()
    if tool == WRITE_HARMONY_TOOL:
        return write_harmony_schema(_section_bars(state, section_id))
    if tool == WRITE_PART_TOOL:
        # The widest gate: a replayed part may declare techniques even where
        # the original call did not offer them.
        return write_part_schema(techniques=True)
    if tool == PLAN_LYRICS_TOOL:
        return plan_lyrics_schema(
            _section_ids(state), sorted(RELATIONSHIP_DEFINITIONS)
        )
    if tool == WRITE_LYRICS_TOOL:
        # Every singing voice in the spec — wider than one section's roster,
        # which is fine for a replay experiment.
        return write_lyrics_schema([voice.voice_id for voice in spec.singing_voices])
    if tool == OBSERVE_DEVICES_TOOL:
        return observe_devices_schema()
    if tool == REWRITE_BARS_TOOL:
        # The widest gate again: the original call offered only the flagged
        # bars, which the log does not record — a replay may rewrite any bar.
        return rewrite_bars_schema(list(range(1, 129)))
    if tool == REVIEW_TOOL:
        return review_schema()
    raise CadenzraError(f"no schema is registered for the tool {tool!r}")


def _section_bars(state: PipelineState | None, section_id: str | None) -> int:
    if state is None or state.structure is None:
        raise CadenzraError(
            "replaying this turn needs the run's structure plan; the run dir "
            "has no state.json with a structure in it"
        )
    if section_id is None:
        raise CadenzraError("the logged turn names no section to rebuild bars from")
    return state.structure.sections_by_id[section_id].bars


def _section_ids(state: PipelineState | None) -> list[str]:
    if state is None or state.structure is None:
        raise CadenzraError(
            "replaying this turn needs the run's structure plan; the run dir "
            "has no state.json with a structure in it"
        )
    return [section.section_id for section in state.structure.sections]
