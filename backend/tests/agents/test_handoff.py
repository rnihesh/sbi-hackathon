"""Human-handoff tool + escalation backstop.

Covers the agent-side of the "knows when to step aside" flow: the shared
``request_human_handoff`` tool (row creation, dedup guard, anonymous prospects,
customer notification), the deterministic backstop phrase matcher, and the
prompt-nudge injection into the specialist system prompt (without ever
auto-creating a row).
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import acquisition, adoption, engagement
from app.agents.handoff_tools import (
    HANDOFF_BACKSTOP_NUDGE,
    HANDOFF_TOOL_GUIDANCE,
    build_handoff_tools,
    handoff_backstop_triggered,
)
from app.agents.state import new_state
from app.agents.supervisor import run_specialist, supervisor_node
from app.models.customer import Customer
from app.models.engagement import Notification
from app.models.enums import HandoffStatus, NotificationKind
from app.models.handoff import HandoffRequest
from tests.agents.conftest import FakeRouter, ScriptedHandler


def _handoff_tool(agent_name: str = "engagement"):  # type: ignore[no-untyped-def]
    return {t.name: t for t in build_handoff_tools(agent_name)}["request_human_handoff"]


async def _customer(db: AsyncSession) -> Customer:
    customer = Customer(full_name="Handoff Tester")
    db.add(customer)
    await db.commit()
    return customer


# ---------------------------------------------------------------------------
# Tool wiring
# ---------------------------------------------------------------------------


def test_handoff_tool_wired_into_all_specialists() -> None:
    for agent in (acquisition, adoption, engagement):
        assert "request_human_handoff" in agent._TOOLS


# ---------------------------------------------------------------------------
# Tool behaviour
# ---------------------------------------------------------------------------


async def test_request_human_handoff_creates_row(make_ctx, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    customer = await _customer(db)
    ctx = await make_ctx(
        FakeRouter(ScriptedHandler()), customer_id=customer.id, conversation_id="conv-1"
    )
    state = new_state(conversation_id="conv-1", customer_id=str(customer.id), user_text="human")

    result = await _handoff_tool().impl(
        ctx, state, {"reason": "Wants to dispute a charge", "urgency": "high"}
    )

    assert result["created"] is True
    assert result["status"] == "open"
    assert result["urgency"] == "high"

    row = await db.scalar(
        sa.select(HandoffRequest).where(HandoffRequest.id == result["handoff_id"])
    )
    assert row is not None
    assert row.customer_id == customer.id
    assert row.conversation_id == "conv-1"
    assert row.reason == "Wants to dispute a charge"
    assert row.status == HandoffStatus.OPEN

    # Structured output carries the handoff so the live feed can publish it.
    assert state["structured"]["handoffs"][0]["id"] == result["handoff_id"]

    # An authenticated customer is notified a human is coming.
    note = await db.scalar(
        sa.select(Notification).where(Notification.customer_id == customer.id)
    )
    assert note is not None
    assert note.kind == NotificationKind.SYSTEM
    assert "relationship manager" in note.title.lower()


async def test_request_human_handoff_defaults_urgency_and_reason(  # type: ignore[no-untyped-def]
    make_ctx, db: AsyncSession
) -> None:
    customer = await _customer(db)
    ctx = await make_ctx(
        FakeRouter(ScriptedHandler()), customer_id=customer.id, conversation_id="c"
    )
    state = new_state(conversation_id="c", customer_id=str(customer.id), user_text="human")

    result = await _handoff_tool().impl(ctx, state, {"reason": "   ", "urgency": "bogus"})
    assert result["created"] is True
    assert result["urgency"] == "normal"  # unknown urgency coerced
    row = await db.scalar(
        sa.select(HandoffRequest).where(HandoffRequest.id == result["handoff_id"])
    )
    assert row is not None
    assert row.reason  # blank reason backfilled with a sensible default


async def test_request_human_handoff_dedup_guard(make_ctx, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    customer = await _customer(db)
    ctx = await make_ctx(
        FakeRouter(ScriptedHandler()), customer_id=customer.id, conversation_id="c"
    )
    state = new_state(conversation_id="c", customer_id=str(customer.id), user_text="human")

    first = await _handoff_tool().impl(ctx, state, {"reason": "first", "urgency": "normal"})
    second = await _handoff_tool().impl(ctx, state, {"reason": "second", "urgency": "high"})

    assert first["created"] is True
    assert second["created"] is False
    assert second["duplicate"] is True
    assert second["handoff_id"] == first["handoff_id"]

    count = await db.scalar(
        sa.select(sa.func.count()).select_from(HandoffRequest).where(
            HandoffRequest.conversation_id == "c"
        )
    )
    assert count == 1


async def test_request_human_handoff_anonymous_prospect(make_ctx, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    ctx = await make_ctx(
        FakeRouter(ScriptedHandler()), customer_id=None, conversation_id="prospect-9"
    )
    state = new_state(conversation_id="prospect-9", customer_id=None, user_text="human")

    result = await _handoff_tool("acquisition").impl(
        ctx, state, {"reason": "Prospect wants to speak to a banker"}
    )
    assert result["created"] is True

    row = await db.scalar(
        sa.select(HandoffRequest).where(HandoffRequest.id == result["handoff_id"])
    )
    assert row is not None
    assert row.customer_id is None
    assert row.conversation_id == "prospect-9"

    # No customer -> no notification row created.
    notes = (await db.execute(sa.select(Notification))).scalars().all()
    assert notes == []


# ---------------------------------------------------------------------------
# Deterministic backstop
# ---------------------------------------------------------------------------


def test_handoff_backstop_triggered_phrases() -> None:
    positives = [
        "I want to talk to a human",
        "Can I SPEAK TO SOMEONE please",
        "let me talk to an agent",
        "I have a complaint about my card",
        "This looks like fraud",
        "mujhe kisi insaan se baat karni hai",
        "yeh ek shikayat hai",
    ]
    for phrase in positives:
        assert handoff_backstop_triggered(phrase) is True, phrase

    negatives = ["what is my balance", "help me set up UPI", "", None]
    for phrase in negatives:
        assert handoff_backstop_triggered(phrase) is False, phrase


async def test_backstop_injects_nudge_into_system(make_ctx, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    """When the backstop fires, the specialist system prompt gains the stronger
    nudge - and the guidance is present regardless - but no row is auto-created."""
    router = FakeRouter(ScriptedHandler(default_text="Sure, I'll get someone."))
    ctx = await make_ctx(router, customer_id=None, conversation_id="c")

    def _system_builder(_ctx, _state, _profile, _memories):  # type: ignore[no-untyped-def]
        return "BASE SYSTEM"

    state = new_state(conversation_id="c", customer_id=None, user_text="I want to talk to a human")
    await run_specialist(
        state,
        {"configurable": {"ctx": ctx}},
        agent_name="engagement",
        node_name="engagement",
        system_builder=_system_builder,
        tools={},
    )

    systems = [c["system"] for c in router.calls if c.get("system")]
    assert any(HANDOFF_TOOL_GUIDANCE in s for s in systems)
    assert any(HANDOFF_BACKSTOP_NUDGE in s for s in systems)

    # Backstop only nudges - it must NOT deterministically create a handoff row.
    count = await db.scalar(sa.select(sa.func.count()).select_from(HandoffRequest))
    assert count == 0


async def test_guidance_present_without_backstop(make_ctx, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    router = FakeRouter(ScriptedHandler(default_text="Here you go."))
    ctx = await make_ctx(router, customer_id=None, conversation_id="c")

    def _system_builder(_ctx, _state, _profile, _memories):  # type: ignore[no-untyped-def]
        return "BASE SYSTEM"

    state = new_state(conversation_id="c", customer_id=None, user_text="what products do you have")
    await run_specialist(
        state,
        {"configurable": {"ctx": ctx}},
        agent_name="acquisition",
        node_name="acquisition",
        system_builder=_system_builder,
        tools={},
    )

    systems = [c["system"] for c in router.calls if c.get("system")]
    assert any(HANDOFF_TOOL_GUIDANCE in s for s in systems)
    # A non-triggering message gets guidance but not the stronger backstop nudge.
    assert not any(HANDOFF_BACKSTOP_NUDGE in s for s in systems)


async def test_supervisor_reroutes_smalltalk_handoff_to_specialist(  # type: ignore[no-untyped-def]
    make_ctx, db: AsyncSession
) -> None:
    """A "talk to a human" turn the classifier would call small talk gets forced
    onto a tool-capable specialist (small talk has no tools)."""
    customer = await _customer(db)
    ctx = await make_ctx(
        FakeRouter(ScriptedHandler()), customer_id=customer.id, conversation_id="c"
    )
    state = new_state(
        conversation_id="c", customer_id=str(customer.id), user_text="I want to talk to a human"
    )
    out = await supervisor_node(state, {"configurable": {"ctx": ctx}})
    # With a customer in context this lands on engagement (a handoff-capable specialist).
    assert out["intent"] == "engagement"


async def test_supervisor_reroutes_anonymous_handoff_to_acquisition(  # type: ignore[no-untyped-def]
    make_ctx, db: AsyncSession
) -> None:
    ctx = await make_ctx(FakeRouter(ScriptedHandler()), customer_id=None, conversation_id="c")
    state = new_state(conversation_id="c", customer_id=None, user_text="I have a complaint")
    out = await supervisor_node(state, {"configurable": {"ctx": ctx}})
    # No customer -> the needs-customer guard sends engagement to acquisition, which
    # also carries the handoff tool. Either way it never stays on small talk.
    assert out["intent"] == "acquisition"
