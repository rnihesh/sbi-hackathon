"""Supervisor routing + full-graph run (tracing rows, policy pass)."""

from __future__ import annotations

import sqlalchemy as sa
from langgraph.checkpoint.memory import MemorySaver

from app.agents.graph import build_graph
from app.agents.state import new_state, turn_input
from app.agents.supervisor import route_intent, supervisor_node
from app.llm.base import ToolCall
from app.models.customer import Customer
from app.models.tracing import AgentStep
from tests.agents.conftest import FakeRouter, ScriptedHandler, make_response


def _classify_router(intent: str) -> FakeRouter:
    return FakeRouter(
        ScriptedHandler(
            queues={"supervisor:classify": [make_response(f'{{"intent": "{intent}"}}')]},
            default_text="A helpful, compliant reply.",
        )
    )


async def test_supervisor_routes_each_intent(make_ctx, db) -> None:  # type: ignore[no-untyped-def]
    # A real customer so adoption/engagement don't fall back to acquisition.
    customer = Customer(full_name="Router User")
    db.add(customer)
    await db.flush()

    cases = {
        "acquisition": (None, "I want to open a savings account"),
        "adoption": (customer.id, "help me set up UPI"),
        "engagement": (customer.id, "I just got a big bonus"),
        "smalltalk": (None, "hi who are you"),
    }
    for expected, (cid, text) in cases.items():
        ctx = await make_ctx(_classify_router(expected), customer_id=cid)
        state = new_state(
            conversation_id="c", customer_id=str(cid) if cid else None, user_text=text
        )
        update = await supervisor_node(state, {"configurable": {"ctx": ctx}})
        state.update(update)  # type: ignore[typeddict-item]
        assert route_intent(state) == expected


async def test_full_graph_smalltalk_writes_trace_and_policy(  # type: ignore[no-untyped-def]
    make_ctx, sessionmaker_test
) -> None:
    handler = ScriptedHandler(
        queues={"supervisor:classify": [make_response('{"intent": "smalltalk"}')]},
        default_text="Hello! I'm Sarathi, your banking assistant.",
    )
    ctx = await make_ctx(FakeRouter(handler))
    graph = build_graph(MemorySaver())

    state = new_state(conversation_id="c-flow", customer_id=None, user_text="hi who are you")
    out = await graph.ainvoke(
        state, config={"configurable": {"ctx": ctx, "thread_id": "c-flow"}}
    )

    assert out["intent"] == "smalltalk"
    assert out["final_text"]

    # Trace rows exist for this run (classify + smalltalk answer + guardrail).
    async with sessionmaker_test() as session:
        steps = list(
            (
                await session.scalars(
                    sa.select(AgentStep).where(AgentStep.run_id == ctx.tracer.run_id)
                )
            ).all()
        )
    names = {s.name for s in steps}
    assert "classify_intent" in names
    assert "policy_check" in names
    assert len(steps) >= 3


async def test_full_graph_streams_events(make_ctx) -> None:  # type: ignore[no-untyped-def]
    from app.agents.context import EventEmitter

    emitter = EventEmitter()
    handler = ScriptedHandler(
        queues={"supervisor:classify": [make_response('{"intent": "smalltalk"}')]},
        default_text="Sure, I can help you with that today.",
    )
    ctx = await make_ctx(FakeRouter(handler), emitter=emitter)
    graph = build_graph(MemorySaver())
    state = new_state(conversation_id="c-stream", customer_id=None, user_text="hello")

    events: list[dict] = []

    async def _collect() -> None:
        async for ev in emitter.stream():
            events.append(ev)

    import asyncio

    collector = asyncio.create_task(_collect())
    await graph.ainvoke(state, config={"configurable": {"ctx": ctx, "thread_id": "c-stream"}})
    await emitter.close()
    await collector

    types = {e["type"] for e in events}
    assert "agent" in types
    assert "token" in types  # final answer streamed as token deltas


async def test_multiturn_onboarding_scratch_persists(make_ctx) -> None:  # type: ignore[no-untyped-def]
    """KYC collected on turn 1 must survive into turn 2 via the checkpointer."""
    handler = ScriptedHandler(
        queues={
            "supervisor:classify": [
                make_response('{"intent": "acquisition"}'),
                make_response('{"intent": "acquisition"}'),
            ],
            "acquisition:loop": [
                # turn 1: collect the name, then finish
                make_response(
                    "", tool_calls=[
                        ToolCall(name="collect_kyc_field",
                                 args={"field": "name", "value": "Rahul Sharma"})
                    ]
                ),
                make_response("Thanks Rahul, what's your phone number?"),
                # turn 2: no tools, just continue
                make_response("Got it, let's continue your onboarding."),
            ],
        },
        default_text="Onboarding in progress.",
    )
    ctx = await make_ctx(FakeRouter(handler))
    graph = build_graph(MemorySaver())
    tid = "c-onboard"
    cfg = {"configurable": {"ctx": ctx, "thread_id": tid}}

    await graph.ainvoke(
        turn_input(conversation_id=tid, customer_id=None,
                   user_text="I want to open an account, I'm Rahul Sharma"),
        config=cfg,
    )
    await graph.ainvoke(
        turn_input(conversation_id=tid, customer_id=None, user_text="continue"),
        config=cfg,
    )

    snapshot = await graph.aget_state(cfg)
    assert snapshot.values["scratch"]["kyc"]["name"] == "Rahul Sharma"
    # Conversation history accumulated across both turns.
    assert len(snapshot.values["messages"]) >= 3
