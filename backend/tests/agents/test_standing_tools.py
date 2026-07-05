"""Standing-instruction agent tools: HITL proposal path, no direct LLM writes."""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

import app.agents.entrypoints as ep
from app.agents import adoption
from app.agents.standing_tools import build_standing_tools
from app.agents.state import new_state
from app.models.banking import Account
from app.models.customer import Customer
from app.models.engagement import Notification, Proposal
from app.models.enums import (
    AccountType,
    GoalStatus,
    NotificationKind,
    ProposalKind,
    ProposalStatus,
)
from app.models.goal import SavingsGoal
from app.models.standing import StandingInstruction
from tests.agents.conftest import FakeRouter, ScriptedHandler

RUPEE = 100


def _tools(agent_name: str) -> dict[str, Any]:
    return {t.name: t for t in build_standing_tools(agent_name)}


async def _customer_with_account_and_goal(
    db: AsyncSession, *, balance_paise: int = 20_000 * RUPEE
) -> tuple[Customer, Account, SavingsGoal]:
    customer = Customer(full_name="Standing Tool Tester")
    db.add(customer)
    await db.flush()
    account = Account(
        customer_id=customer.id, type=AccountType.SAVINGS, balance_paise=balance_paise
    )
    db.add(account)
    goal = SavingsGoal(
        customer_id=customer.id,
        name="Emergency fund",
        target_paise=50_000 * RUPEE,
        baseline_paise=0,
        status=GoalStatus.ACTIVE,
    )
    db.add(goal)
    await db.flush()
    await db.commit()
    return customer, account, goal


def test_standing_tools_wired_into_adoption() -> None:
    assert "setup_standing_instruction" in adoption._TOOLS
    assert "list_standing_instructions" in adoption._TOOLS


async def test_setup_creates_proposal_not_instruction(make_ctx, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    customer, _account, _goal = await _customer_with_account_and_goal(db)
    ctx = await make_ctx(FakeRouter(ScriptedHandler()), customer_id=customer.id)
    state = new_state(conversation_id="c", customer_id=str(customer.id), user_text="auto save")

    result = await _tools("adoption")["setup_standing_instruction"].impl(
        ctx, state, {"purpose": "goal", "amount_rupees": 2_000, "cadence": "monthly",
                     "goal_name": "Emergency"}
    )
    assert result["proposed"] is True
    await db.commit()

    proposal = await db.scalar(sa.select(Proposal).where(Proposal.customer_id == customer.id))
    assert proposal is not None
    assert proposal.kind is ProposalKind.ACTION
    assert proposal.action["kind"] == "create_standing_instruction"
    assert proposal.action["amount_paise"] == 2_000 * RUPEE
    assert proposal.action["cadence"] == "monthly"

    # The LLM path must NOT create the real row directly.
    rows = (await db.scalars(sa.select(StandingInstruction))).all()
    assert list(rows) == []


async def test_setup_requires_goal_for_goal_purpose(make_ctx, db: AsyncSession) -> None:  # type: ignore[no-untyped-def]
    customer, _account, _goal = await _customer_with_account_and_goal(db)
    ctx = await make_ctx(FakeRouter(ScriptedHandler()), customer_id=customer.id)
    state = new_state(conversation_id="c", customer_id=str(customer.id), user_text="save")

    result = await _tools("adoption")["setup_standing_instruction"].impl(
        ctx, state, {"purpose": "goal", "amount_rupees": 2_000, "cadence": "monthly",
                     "goal_name": "nonexistent"}
    )
    assert result["proposed"] is False


async def test_proposal_execution_creates_instruction(  # type: ignore[no-untyped-def]
    make_ctx, db: AsyncSession, sessionmaker_test, monkeypatch
) -> None:
    monkeypatch.setattr(ep, "get_sessionmaker", lambda: sessionmaker_test)
    customer, _account, _goal = await _customer_with_account_and_goal(db)
    ctx = await make_ctx(FakeRouter(ScriptedHandler()), customer_id=customer.id)
    state = new_state(conversation_id="c", customer_id=str(customer.id), user_text="auto save")

    result = await _tools("adoption")["setup_standing_instruction"].impl(
        ctx, state, {"purpose": "goal", "amount_rupees": 2_000, "cadence": "monthly",
                     "goal_name": "Emergency"}
    )
    await db.commit()
    proposal_id = result["proposal_id"]

    exec_result = await ep.execute_proposal(proposal_id, approver="rm@bank.example")
    assert exec_result.status == "executed"
    assert exec_result.action_kind == "create_standing_instruction"

    async with sessionmaker_test() as session:
        instruction = await session.scalar(
            sa.select(StandingInstruction).where(
                StandingInstruction.customer_id == customer.id
            )
        )
        assert instruction is not None
        assert instruction.amount_paise == 2_000 * RUPEE
        assert instruction.goal_id is not None

        proposal = await session.get(Proposal, uuid.UUID(proposal_id))
        assert proposal is not None
        assert proposal.status is ProposalStatus.EXECUTED

        note = await session.scalar(
            sa.select(Notification).where(
                Notification.customer_id == customer.id,
                Notification.kind == NotificationKind.SYSTEM,
            )
        )
        assert note is not None
        assert note.link == "/app/home"
