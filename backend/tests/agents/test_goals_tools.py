"""Savings-goal agent tools: wiring into both specialists + create/read behaviour.

Exercises the tool implementations directly against a real test DB with a
FakeRouter-backed context (the same convention as ``test_acquisition_gate``),
plus asserts the tools are actually wired into both agents' toolsets.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import acquisition, adoption
from app.agents.goal_tools import build_goal_tools
from app.agents.state import new_state
from app.models.banking import Account
from app.models.customer import Customer
from app.models.enums import AccountType
from app.models.goal import SavingsGoal
from tests.agents.conftest import FakeRouter, ScriptedHandler

RUPEE = 100


def _tools(agent_name: str) -> dict[str, Any]:
    return {t.name: t for t in build_goal_tools(agent_name)}


async def _customer(db: AsyncSession, *, balance_paise: int = 0) -> Customer:
    customer = Customer(full_name="Goal Tester")
    db.add(customer)
    await db.flush()
    if balance_paise:
        db.add(
            Account(customer_id=customer.id, type=AccountType.SAVINGS, balance_paise=balance_paise)
        )
    await db.commit()
    return customer


def test_goal_tools_wired_into_both_agents() -> None:
    for agent in (adoption, acquisition):
        assert "get_savings_goals" in agent._TOOLS
        assert "create_savings_goal" in agent._TOOLS


async def test_create_savings_goal_tool_persists(make_ctx, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    customer = await _customer(db, balance_paise=100 * RUPEE)
    ctx = await make_ctx(FakeRouter(ScriptedHandler()), customer_id=customer.id)
    state = new_state(conversation_id="c", customer_id=str(customer.id), user_text="save")

    result = await _tools("adoption")["create_savings_goal"].impl(
        ctx, state, {"name": "New phone", "target_rupees": 500}
    )
    assert result["created"] is True
    assert result["target_paise"] == 500 * RUPEE

    goal = await db.scalar(sa.select(SavingsGoal).where(SavingsGoal.customer_id == customer.id))
    assert goal is not None
    assert goal.name == "New phone"
    assert goal.baseline_paise == 100 * RUPEE  # captured at creation


async def test_get_savings_goals_tool_reports_progress(make_ctx, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    customer = await _customer(db, balance_paise=10_000 * RUPEE)
    ctx = await make_ctx(FakeRouter(ScriptedHandler()), customer_id=customer.id)
    state = new_state(conversation_id="c", customer_id=str(customer.id), user_text="goals")

    await _tools("adoption")["create_savings_goal"].impl(
        ctx, state, {"name": "Trip", "target_rupees": 5_000}
    )
    # Balance grows by ₹2,500 after the goal was set.
    db.add(Account(customer_id=customer.id, type=AccountType.SAVINGS, balance_paise=2_500 * RUPEE))
    await db.flush()

    result = await _tools("adoption")["get_savings_goals"].impl(ctx, state, {})
    assert result["active_count"] == 1
    assert result["max_active"] == 5
    goal = result["goals"][0]
    assert goal["progress_paise"] == 2_500 * RUPEE
    assert goal["pct"] == 50.0
    assert goal["status"] == "active"


async def test_create_savings_goal_tool_requires_customer(make_ctx) -> None:  # type: ignore[no-untyped-def]
    ctx = await make_ctx(FakeRouter(ScriptedHandler()), customer_id=None)
    state = new_state(conversation_id="c", customer_id=None, user_text="save 1000")
    result = await _tools("acquisition")["create_savings_goal"].impl(
        ctx, state, {"name": "x", "target_rupees": 1_000}
    )
    assert result["created"] is False
    assert "account" in result["error"].lower()


async def test_create_savings_goal_tool_respects_cap(make_ctx, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    customer = await _customer(db)
    ctx = await make_ctx(FakeRouter(ScriptedHandler()), customer_id=customer.id)
    state = new_state(conversation_id="c", customer_id=str(customer.id), user_text="goals")
    tools = _tools("adoption")

    for i in range(5):
        created = await tools["create_savings_goal"].impl(
            ctx, state, {"name": f"g{i}", "target_rupees": 100}
        )
        assert created["created"] is True

    sixth = await tools["create_savings_goal"].impl(
        ctx, state, {"name": "sixth", "target_rupees": 100}
    )
    assert sixth["created"] is False
    assert "active goals" in sixth["error"].lower()
