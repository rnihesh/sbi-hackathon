"""Typed graph state and streamed event shapes for the agent mesh.

``AgentState`` holds only JSON-serialisable values so the Postgres checkpointer
can persist it across turns (this is what makes multi-turn onboarding resume).
Non-serialisable per-run dependencies (DB session, router, tracer) travel out of
band on :class:`~app.agents.context.AgentContext`, passed via the graph config.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

Intent = Literal["acquisition", "adoption", "engagement", "smalltalk"]


class ChatTurn(TypedDict):
    role: str
    content: str


class AgentState(TypedDict, total=False):
    """Serialisable LangGraph state (channels merged last-value)."""

    messages: list[ChatTurn]        # redacted conversation history for the LLM
    user_text: str                  # current turn (raw; redacted before LLM use)
    customer_id: str | None
    conversation_id: str
    trigger: str                    # "chat" | "event"
    event: dict[str, Any] | None    # event payload for the event path
    intent: str                     # set by supervisor
    current_agent: str              # active specialist node name
    proposals_out: list[str]        # proposal ids created this run
    scratch: dict[str, Any]         # per-agent working memory (persists across turns)
    structured: dict[str, Any]      # structured payloads (walkthrough, detected events…)
    final_text: str                 # policy-checked outbound reply


# Streamed event `type` values yielded by run_chat_turn.
EventType = Literal[
    "run_started", "agent", "tool_start", "tool_end", "token", "structured", "done", "error"
]


def scratch_of(state: AgentState) -> dict[str, Any]:
    """Return the (lazily-created) mutable scratch dict."""
    scratch = state.get("scratch")
    if scratch is None:
        scratch = {}
        state["scratch"] = scratch
    return scratch


def structured_bag(state: AgentState) -> dict[str, Any]:
    """Return the (lazily-created) structured-payload dict."""
    bag = state.get("structured")
    if bag is None:
        bag = {}
        state["structured"] = bag
    return bag


def append_structured(state: AgentState, key: str, value: Any) -> None:
    """Append ``value`` to a list under ``key`` in the structured payload."""
    bag = structured_bag(state)
    existing = bag.get(key)
    if not isinstance(existing, list):
        existing = []
        bag[key] = existing
    existing.append(value)


def set_structured(state: AgentState, key: str, value: Any) -> None:
    structured_bag(state)[key] = value


def append_proposal(state: AgentState, proposal_id: str) -> None:
    """Record a created proposal id on the run state."""
    proposals = state.get("proposals_out")
    if proposals is None:
        proposals = []
        state["proposals_out"] = proposals
    proposals.append(proposal_id)


def new_state(
    *,
    conversation_id: str,
    customer_id: str | None,
    user_text: str,
    trigger: str = "chat",
    event: dict[str, Any] | None = None,
    scratch: dict[str, Any] | None = None,
) -> AgentState:
    """Build a fresh, fully-initialised state (single-shot / first turn / tests)."""
    return AgentState(
        messages=[],
        user_text=user_text,
        customer_id=customer_id,
        conversation_id=conversation_id,
        trigger=trigger,
        event=event,
        intent="",
        current_agent="",
        proposals_out=[],
        scratch=scratch or {},
        structured={},
        final_text="",
    )


def turn_input(
    *,
    conversation_id: str,
    customer_id: str | None,
    user_text: str,
    trigger: str = "chat",
    event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the *partial* input for one turn on a checkpointed thread.

    Crucially omits ``messages`` and ``scratch`` so the checkpointer's accumulated
    values persist across turns (this is what makes multi-turn onboarding resume).
    ``customer_id`` is only set when known, so a customer discovered on a prior
    turn isn't clobbered back to ``None``. Per-turn ephemerals are reset.
    """
    payload: dict[str, Any] = {
        "conversation_id": conversation_id,
        "user_text": user_text,
        "trigger": trigger,
        "event": event,
        "intent": "",
        "current_agent": "",
        "proposals_out": [],
        "structured": {},
        "final_text": "",
    }
    if customer_id is not None:
        payload["customer_id"] = customer_id
    return payload
