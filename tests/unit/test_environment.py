"""Phase 0 gate: the dependency stack behaves as the design assumes.

Two assumptions elsewhere in the system rest on these:
LangGraph drives a Pydantic-model state (docs/02), and exact `Fraction` time
survives the state dumps written to `out/<run-id>/` (docs/03, docs/07).
"""

from fractions import Fraction

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel


class _Counter(BaseModel):
    n: int = 0


def test_langgraph_drives_pydantic_state() -> None:
    graph = StateGraph(_Counter)
    graph.add_node("inc", lambda state: {"n": state.n + 1})
    graph.add_edge(START, "inc")
    graph.add_edge("inc", END)

    assert graph.compile().invoke(_Counter(n=1)) == {"n": 2}


class _Timed(BaseModel):
    offset: Fraction


def test_fraction_survives_json_round_trip() -> None:
    original = _Timed(offset=Fraction(7, 8))
    restored = _Timed.model_validate_json(original.model_dump_json())

    assert restored.offset == Fraction(7, 8)
