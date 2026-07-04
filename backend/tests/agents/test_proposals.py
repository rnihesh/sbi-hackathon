"""Human-in-the-loop proposal executor tests."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

import app.agents.entrypoints as ep
from app.agents.actions import create_proposal
from app.models.customer import Customer
from app.models.engagement import Notification, Nudge, Proposal
from app.models.enums import NotificationKind, ProposalStatus


async def test_execute_proposal_send_nudge(  # type: ignore[no-untyped-def]
    db, sessionmaker_test, monkeypatch
) -> None:
    monkeypatch.setattr(ep, "get_sessionmaker", lambda: sessionmaker_test)

    customer = Customer(full_name="HITL Customer")
    db.add(customer)
    await db.flush()
    proposal = await create_proposal(
        db, customer_id=customer.id, agent="adoption", kind="nudge",
        title="Try UPI AutoPay", body="Automate your bills.",
        action={"kind": "send_nudge", "cta": {"label": "Set up"}},
    )
    await db.commit()

    result = await ep.execute_proposal(str(proposal.id), approver="rm@bank.example")
    assert result.status == "executed"
    assert result.action_kind == "send_nudge"

    async with sessionmaker_test() as session:
        refreshed = await session.get(Proposal, proposal.id)
        assert refreshed.status is ProposalStatus.EXECUTED
        assert refreshed.decided_by == "rm@bank.example"
        nudges = list(
            (
                await session.scalars(
                    sa.select(Nudge).where(Nudge.proposal_id == proposal.id)
                )
            ).all()
        )
        assert len(nudges) == 1


async def test_execute_proposal_notifies_customer(  # type: ignore[no-untyped-def]
    db, sessionmaker_test, monkeypatch
) -> None:
    monkeypatch.setattr(ep, "get_sessionmaker", lambda: sessionmaker_test)

    customer = Customer(full_name="Notified Customer")
    db.add(customer)
    await db.flush()
    proposal = await create_proposal(
        db, customer_id=customer.id, agent="engagement", kind="product_offer",
        title="A pre-approved FD for you", body="Lock in a better rate.",
        action={"kind": "product_offer", "product_code": "fd_std"},
    )
    await db.commit()

    await ep.execute_proposal(str(proposal.id), approver="rm@bank.example")

    async with sessionmaker_test() as session:
        notes = list(
            (
                await session.scalars(
                    sa.select(Notification).where(Notification.customer_id == customer.id)
                )
            ).all()
        )
    assert len(notes) == 1
    assert notes[0].kind is NotificationKind.OFFER
    assert notes[0].title == "A pre-approved FD for you"
    assert notes[0].link == "/app/nudges"
    assert notes[0].read is False


async def test_execute_proposal_rejects_unknown_action(  # type: ignore[no-untyped-def]
    db, sessionmaker_test, monkeypatch
) -> None:
    monkeypatch.setattr(ep, "get_sessionmaker", lambda: sessionmaker_test)

    customer = Customer(full_name="HITL Customer 2")
    db.add(customer)
    await db.flush()
    proposal = await create_proposal(
        db, customer_id=customer.id, agent="adoption", kind="action",
        title="Mystery", body="?", action={"kind": "teleport"},
    )
    await db.commit()

    with pytest.raises(NotImplementedError):
        await ep.execute_proposal(str(proposal.id), approver="rm@bank.example")


async def test_execute_proposal_twice_is_rejected(  # type: ignore[no-untyped-def]
    db, sessionmaker_test, monkeypatch
) -> None:
    monkeypatch.setattr(ep, "get_sessionmaker", lambda: sessionmaker_test)

    customer = Customer(full_name="HITL Customer 3")
    db.add(customer)
    await db.flush()
    proposal = await create_proposal(
        db, customer_id=customer.id, agent="engagement", kind="nudge",
        title="Congrats", body="On your bonus!", action={"kind": "send_nudge"},
    )
    await db.commit()

    await ep.execute_proposal(str(proposal.id), approver="rm@bank.example")
    with pytest.raises(ValueError, match="already"):
        await ep.execute_proposal(str(proposal.id), approver="rm@bank.example")


def test_normalize_action_kind_passthrough() -> None:
    from app.agents.actions import normalize_action_kind

    assert normalize_action_kind("send_email", "email") == "send_email"
    assert normalize_action_kind("product_offer", "offer") == "product_offer"


def test_normalize_action_kind_coerces_unexecutable() -> None:
    from app.agents.actions import normalize_action_kind

    # The live-run bug: inner kind "action" had no executor and stranded
    # the proposal as unapprovable.
    assert normalize_action_kind("action", "email") == "send_email"
    assert normalize_action_kind(None, "product_offer") == "product_offer"
    assert normalize_action_kind("garbage", "unknown-kind") == "send_nudge"
