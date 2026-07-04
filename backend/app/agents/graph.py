"""LangGraph wiring for the Sarathi agent mesh.

Topology::

    START → supervisor ─(intent)→ acquisition ┐
                                  adoption     ├→ synthesize → END
                                  engagement   │
                                  smalltalk    ┘

The supervisor classifies intent and routes; the chosen specialist runs its tool
loop; ``synthesize`` applies guardrails, disclosures, audit, and memory, then
streams the reply. Compiled once with the durable Postgres checkpointer.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.acquisition import acquisition_node
from app.agents.adoption import adoption_node
from app.agents.checkpointer import init_checkpointer
from app.agents.engagement import engagement_node
from app.agents.state import AgentState
from app.agents.supervisor import (
    route_intent,
    smalltalk_node,
    supervisor_node,
    synthesize_node,
)

_compiled: Any | None = None


def build_graph(checkpointer: Any | None = None) -> Any:
    """Build and compile the agent graph (optionally with a checkpointer).

    ``graph`` is typed ``Any``: LangGraph's ``add_node`` generics don't accept our
    ``(state, config)`` node signatures under mypy strict, and the architecture
    blueprint permits pragmatic typing in the agent glue layer.
    """
    graph: Any = StateGraph(AgentState)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("acquisition", acquisition_node)
    graph.add_node("adoption", adoption_node)
    graph.add_node("engagement", engagement_node)
    graph.add_node("smalltalk", smalltalk_node)
    graph.add_node("synthesize", synthesize_node)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        route_intent,
        {
            "acquisition": "acquisition",
            "adoption": "adoption",
            "engagement": "engagement",
            "smalltalk": "smalltalk",
        },
    )
    for specialist in ("acquisition", "adoption", "engagement", "smalltalk"):
        graph.add_edge(specialist, "synthesize")
    graph.add_edge("synthesize", END)

    return graph.compile(checkpointer=checkpointer)


async def get_compiled_graph() -> Any:
    """Return the process-wide compiled graph with the Postgres checkpointer."""
    global _compiled
    if _compiled is None:
        checkpointer = await init_checkpointer()
        _compiled = build_graph(checkpointer)
    return _compiled
