"""All LangGraph wiring lives here.

Keeping every edge in one module is the mitigation for framework lock-in: nodes
are plain functions over `PipelineState`, so the framework touches the shape of
the program and not its substance (docs/02).

M2 wires the smallest loop the design contains — generate a voice, validate it,
loop back with feedback — which is enough to exercise budgets, feedback
clearing, and the fail-loud path before any of the larger layers exist.
"""

from functools import partial

from langgraph.graph import END, START, StateGraph

from cadenzra.graph.nodes import (
    Services,
    generate_voice_node,
    validate_voice_node,
    voice_loop_decision,
)
from cadenzra.model.primitives.ids import SectionId, VoiceId
from cadenzra.model.state import PipelineState

GENERATE_VOICE = "generate_voice"
VALIDATE_VOICE = "validate_voice"


def build_voice_graph(
    services: Services, section_id: SectionId, voice_id: VoiceId
) -> object:
    """The generate-validate loop for one (section, voice) pair."""
    graph = StateGraph(PipelineState)

    graph.add_node(
        GENERATE_VOICE,
        partial(
            generate_voice_node,
            services=services,
            section_id=section_id,
            voice_id=voice_id,
        ),
    )
    graph.add_node(
        VALIDATE_VOICE,
        partial(
            validate_voice_node,
            services=services,
            section_id=section_id,
            voice_id=voice_id,
        ),
    )

    graph.add_edge(START, GENERATE_VOICE)
    graph.add_edge(GENERATE_VOICE, VALIDATE_VOICE)
    graph.add_conditional_edges(
        VALIDATE_VOICE,
        partial(
            voice_loop_decision,
            services=services,
            section_id=section_id,
            voice_id=voice_id,
        ),
        {"pass": END, "retry": GENERATE_VOICE},
    )

    return graph.compile()
