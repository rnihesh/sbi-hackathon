"""Streaming synthesis through the graph: real token deltas + guardrail append.

Drives the compiled graph with an ``EventEmitter`` attached (the chat path) and
asserts the final user-facing answer is delivered as incremental provider token
deltas, and that a mandated disclosure the PolicyEngine appends after the stream
completes is emitted as a trailing token event (and lands in ``final_text``).
"""

from __future__ import annotations

import asyncio
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from app.agents.context import EventEmitter
from app.agents.graph import build_graph
from app.agents.state import new_state
from app.models.customer import Customer
from tests.agents.conftest import FakeRouter, ScriptedHandler, make_response

_MF_MARKER = "subject to market risks"


async def _run_with_events(
    ctx: Any, state: Any, thread_id: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    emitter = ctx.emitter
    events: list[dict[str, Any]] = []

    async def _collect() -> None:
        async for ev in emitter.stream():
            events.append(ev)

    collector = asyncio.create_task(_collect())
    graph = build_graph(MemorySaver())
    out = await graph.ainvoke(state, config={"configurable": {"ctx": ctx, "thread_id": thread_id}})
    await emitter.close()
    await collector
    return events, out


async def test_smalltalk_answer_streams_as_incremental_tokens(make_ctx) -> None:  # type: ignore[no-untyped-def]
    handler = ScriptedHandler(
        queues={"supervisor:classify": [make_response('{"intent": "smalltalk"}')]},
        default_text="Sure, I can absolutely help you with that today.",
    )
    ctx = await make_ctx(FakeRouter(handler), emitter=EventEmitter())
    state = new_state(conversation_id="c-stream", customer_id=None, user_text="hi")

    events, out = await _run_with_events(ctx, state, "c-stream")

    token_events = [e for e in events if e["type"] == "token"]
    # Real deltas: the answer arrives across several token events, not one burst.
    assert len(token_events) > 1
    streamed = "".join(e["text"] for e in token_events)
    assert streamed == out["final_text"]
    assert out["final_text"] == "Sure, I can absolutely help you with that today."


async def test_disclosure_appended_after_stream_completes(make_ctx, db) -> None:  # type: ignore[no-untyped-def]
    # A real customer so `adoption` doesn't fall back to acquisition.
    customer = Customer(full_name="Streaming User")
    db.add(customer)
    await db.flush()

    draft = "Here is information about mutual fund investments."
    handler = ScriptedHandler(
        queues={
            "supervisor:classify": [make_response('{"intent": "adoption"}')],
            # loop answers immediately (no tool calls) -> proceeds to final synthesis
            "adoption:loop": [make_response("gathering done")],
            "adoption:final": [make_response(draft)],
        },
        default_text="fallback",
    )
    ctx = await make_ctx(FakeRouter(handler), emitter=EventEmitter(), customer_id=customer.id)
    state = new_state(
        conversation_id="c-disc", customer_id=str(customer.id), user_text="tell me about SIPs"
    )

    events, out = await _run_with_events(ctx, state, "c-disc")

    token_events = [e for e in events if e["type"] == "token"]
    streamed = "".join(e["text"] for e in token_events)

    # The draft streamed as real deltas, and the mandated disclosure was appended
    # AFTER the stream (a trailing token) rather than being part of the model output.
    assert draft in streamed
    assert _MF_MARKER in streamed
    # The full incremental stream equals the compliant final text.
    assert streamed == out["final_text"]
    assert out["final_text"].startswith(draft)
    assert out["final_text"].rstrip().endswith(
        "Read all scheme related documents carefully before investing."
    )
    # The disclosure rode its own trailing token event, emitted post-stream.
    assert any(_MF_MARKER in e["text"] for e in token_events)


async def test_event_path_is_not_streamed(make_ctx) -> None:  # type: ignore[no-untyped-def]
    # No emitter => event/non-streaming path: no token events, answer still synthesised.
    handler = ScriptedHandler(
        queues={"supervisor:classify": [make_response('{"intent": "smalltalk"}')]},
        default_text="A concise, compliant answer.",
    )
    ctx = await make_ctx(FakeRouter(handler))  # emitter defaults to None
    state = new_state(conversation_id="c-evt", customer_id=None, user_text="hello")

    graph = build_graph(MemorySaver())
    out = await graph.ainvoke(state, config={"configurable": {"ctx": ctx, "thread_id": "c-evt"}})

    assert out["final_text"] == "A concise, compliant answer."
