"""``GET /me/activity`` - the account-activity privacy surface.

Sourced from the tamper-evident ``audit_log`` table (see `app.api.v1.customers`'s
module comment for the full allowlist rationale). These tests cover: each allowed
(action, entity) pair renders with the right join and summary text, the excluded
actions never leak through, cross-tenant isolation, ordering, and the ``limit`` cap.

``AuditLog`` rows are constructed directly (not via ``AuditTrail.record``) since
these tests only need rows that exist with the right ``action``/``entity``/
``entity_id``/``payload`` - the hash chain itself is exercised elsewhere
(``tests/agents`` guardrails tests).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.banking import Account
from app.models.crm import Lead
from app.models.engagement import LifeEvent, Notification, Nudge, Proposal
from app.models.enums import (
    AccountStatus,
    AccountType,
    LeadStage,
    LifeEventStatus,
    LifeEventType,
    NotificationKind,
    NudgeStatus,
    ProposalKind,
    ProposalStatus,
)
from app.models.goal import SavingsGoal
from app.models.identity import User
from tests.api.conftest import auth_cookies

_seq = 0


def _audit(
    *,
    action: str,
    entity: str,
    entity_id: str | None,
    payload: dict[str, Any] | None = None,
    ts: datetime | None = None,
    actor: str = "test-actor",
) -> AuditLog:
    global _seq
    _seq += 1
    return AuditLog(
        actor=actor,
        action=action,
        entity=entity,
        entity_id=entity_id,
        payload=payload or {},
        ts=ts or datetime.now(UTC),
        prev_hash="0" * 64,
        hash=f"{_seq:064d}",
    )


async def test_get_activity_requires_auth(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/me/activity")
    assert resp.status_code == 401


async def test_get_activity_404_without_customer_profile(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    user = User(email="no-customer-activity@example.com")
    db.add(user)
    await db.commit()

    resp = await client.get("/api/v1/me/activity", cookies=auth_cookies(user))
    assert resp.status_code == 404


async def test_get_activity_empty_is_honest_empty_list(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer()
    resp = await client.get("/api/v1/me/activity", cookies=auth_cookies(user))
    assert resp.status_code == 200
    assert resp.json() == {"activity": []}


async def test_lead_created_and_kyc_verified_are_included(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    lead = Lead(customer_id=customer.id, source="chat", stage=LeadStage.NEW)
    db.add(lead)
    await db.flush()
    db.add(_audit(action="lead.created", entity="lead", entity_id=str(lead.id)))
    db.add(
        _audit(
            action="kyc.verified",
            entity="lead",
            entity_id=str(lead.id),
            payload={"status": "verified", "reason": "identity verified"},
        )
    )
    await db.commit()

    resp = await client.get("/api/v1/me/activity", cookies=auth_cookies(user))
    assert resp.status_code == 200
    items = resp.json()["activity"]
    actions = {item["action"] for item in items}
    assert "Application started" in actions
    assert "Identity verification" in actions
    verified_item = next(i for i in items if i["action"] == "Identity verification")
    assert "verified" in verified_item["summary"].lower()


async def test_account_opened_is_included_with_humanized_type(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    account = Account(
        customer_id=customer.id,
        type=AccountType.SAVINGS,
        balance_paise=0,
        status=AccountStatus.ACTIVE,
    )
    db.add(account)
    await db.flush()
    db.add(_audit(action="account.opened", entity="account", entity_id=str(account.id)))
    await db.commit()

    resp = await client.get("/api/v1/me/activity", cookies=auth_cookies(user))
    items = resp.json()["activity"]
    assert len(items) == 1
    assert items[0]["action"] == "Account opened"
    assert "savings" in items[0]["summary"].lower()


async def test_goal_created_is_included(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    goal = SavingsGoal(customer_id=customer.id, name="Trip to Goa", target_paise=100_000_00)
    db.add(goal)
    await db.flush()
    db.add(_audit(action="goal.created", entity="savings_goal", entity_id=str(goal.id)))
    await db.commit()

    resp = await client.get("/api/v1/me/activity", cookies=auth_cookies(user))
    items = resp.json()["activity"]
    assert len(items) == 1
    assert items[0]["action"] == "Savings goal created"
    assert "Trip to Goa" in items[0]["summary"]


async def test_nudge_created_is_included(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    nudge = Nudge(
        customer_id=customer.id, title="Try UPI autopay", body="body", status=NudgeStatus.SENT
    )
    db.add(nudge)
    await db.flush()
    db.add(_audit(action="nudge.created", entity="nudge", entity_id=str(nudge.id)))
    await db.commit()

    resp = await client.get("/api/v1/me/activity", cookies=auth_cookies(user))
    items = resp.json()["activity"]
    assert len(items) == 1
    assert items[0]["action"] == "Suggestion for you"
    assert items[0]["summary"] == "Try UPI autopay"


async def test_life_event_recorded_is_included_without_leaking_raw_type(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    event = LifeEvent(
        customer_id=customer.id,
        type=LifeEventType.JOB_CHANGE,
        confidence=0.87,
        status=LifeEventStatus.DETECTED,
    )
    db.add(event)
    await db.flush()
    db.add(_audit(action="life_event.recorded", entity="life_event", entity_id=str(event.id)))
    await db.commit()

    resp = await client.get("/api/v1/me/activity", cookies=auth_cookies(user))
    items = resp.json()["activity"]
    assert len(items) == 1
    assert items[0]["action"] == "Activity noticed"
    # The raw type/confidence must not appear verbatim - just the plain-language phrasing.
    assert "job_change" not in items[0]["summary"]
    assert "0.87" not in items[0]["summary"]


async def test_proposal_executed_is_included_but_created_and_rejected_are_not(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    executed = Proposal(
        customer_id=customer.id,
        agent="engagement",
        kind=ProposalKind.NUDGE,
        title="A new offer for you",
        body="body",
        status=ProposalStatus.EXECUTED,
    )
    rejected = Proposal(
        customer_id=customer.id,
        agent="engagement",
        kind=ProposalKind.NUDGE,
        title="An offer that was rejected",
        body="body",
        status=ProposalStatus.REJECTED,
    )
    db.add_all([executed, rejected])
    await db.flush()
    db.add(_audit(action="proposal.executed", entity="proposal", entity_id=str(executed.id)))
    db.add(_audit(action="proposal.created", entity="proposal", entity_id=str(executed.id)))
    db.add(_audit(action="proposal.created", entity="proposal", entity_id=str(rejected.id)))
    db.add(_audit(action="proposal.rejected", entity="proposal", entity_id=str(rejected.id)))
    await db.commit()

    resp = await client.get("/api/v1/me/activity", cookies=auth_cookies(user))
    items = resp.json()["activity"]
    assert len(items) == 1
    assert items[0]["action"] == "Proposal executed for you"
    assert items[0]["summary"] == "A new offer for you"


async def test_internal_and_private_actions_are_excluded(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    """intent.classified/agent.response (conversation telemetry), churn.scored
    (internal risk score - entity_id IS the customer id, so attribution would be
    trivial, but it is excluded on content grounds), and note.created/note.deleted
    (private staff annotations) must never appear, even though nothing prevents an
    agent from writing them against this customer's own id."""
    user, customer = await make_customer()
    db.add_all(
        [
            _audit(action="intent.classified", entity="conversation", entity_id=str(uuid.uuid4())),
            _audit(action="agent.response", entity="conversation", entity_id=str(uuid.uuid4())),
            _audit(action="churn.scored", entity="customer", entity_id=str(customer.id)),
            _audit(action="note.created", entity="staff_note", entity_id=str(uuid.uuid4())),
            _audit(action="note.deleted", entity="staff_note", entity_id=str(uuid.uuid4())),
        ]
    )
    await db.commit()

    resp = await client.get("/api/v1/me/activity", cookies=auth_cookies(user))
    assert resp.status_code == 200
    assert resp.json()["activity"] == []


async def test_activity_only_returns_own_customer(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer(email="activity-me@example.com")
    _other_user, other_customer = await make_customer(email="activity-other@example.com")

    mine = Nudge(customer_id=customer.id, title="Mine", body="b", status=NudgeStatus.SENT)
    theirs = Nudge(customer_id=other_customer.id, title="Theirs", body="b", status=NudgeStatus.SENT)
    db.add_all([mine, theirs])
    await db.flush()
    db.add(_audit(action="nudge.created", entity="nudge", entity_id=str(mine.id)))
    db.add(_audit(action="nudge.created", entity="nudge", entity_id=str(theirs.id)))
    await db.commit()

    resp = await client.get("/api/v1/me/activity", cookies=auth_cookies(user))
    items = resp.json()["activity"]
    assert len(items) == 1
    assert items[0]["summary"] == "Mine"


async def test_activity_is_reverse_chronological(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    now = datetime.now(UTC)
    goal_old = SavingsGoal(customer_id=customer.id, name="Old goal", target_paise=1000_00)
    goal_new = SavingsGoal(customer_id=customer.id, name="New goal", target_paise=1000_00)
    db.add_all([goal_old, goal_new])
    await db.flush()
    db.add(
        _audit(
            action="goal.created",
            entity="savings_goal",
            entity_id=str(goal_old.id),
            ts=now - timedelta(days=2),
        )
    )
    db.add(
        _audit(
            action="goal.created",
            entity="savings_goal",
            entity_id=str(goal_new.id),
            ts=now - timedelta(minutes=5),
        )
    )
    await db.commit()

    resp = await client.get("/api/v1/me/activity", cookies=auth_cookies(user))
    items = resp.json()["activity"]
    assert [i["summary"] for i in items] == [
        'You created the savings goal "New goal".',
        'You created the savings goal "Old goal".',
    ]


async def test_activity_respects_limit(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    now = datetime.now(UTC)
    for i in range(5):
        nudge = Nudge(
            customer_id=customer.id, title=f"Nudge {i}", body="b", status=NudgeStatus.SENT
        )
        db.add(nudge)
        await db.flush()
        db.add(
            _audit(
                action="nudge.created",
                entity="nudge",
                entity_id=str(nudge.id),
                ts=now - timedelta(minutes=i),
            )
        )
    await db.commit()

    resp = await client.get("/api/v1/me/activity?limit=2", cookies=auth_cookies(user))
    assert resp.status_code == 200
    items = resp.json()["activity"]
    assert len(items) == 2
    assert items[0]["summary"] == "Nudge 0"
    assert items[1]["summary"] == "Nudge 1"


async def test_activity_limit_is_bounded(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer()
    resp = await client.get("/api/v1/me/activity?limit=0", cookies=auth_cookies(user))
    assert resp.status_code == 422
    resp = await client.get("/api/v1/me/activity?limit=101", cookies=auth_cookies(user))
    assert resp.status_code == 422


async def test_activity_ignores_unrelated_notification_rows(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    """Notifications are a separate feature (`/me/notifications`) - the activity
    log is sourced purely from `audit_log`, so an unrelated Notification row with no
    matching audit entry must not surface anything."""
    user, customer = await make_customer()
    db.add(
        Notification(
            customer_id=customer.id,
            kind=NotificationKind.NUDGE,
            title="A notification",
            body="body",
        )
    )
    await db.commit()

    resp = await client.get("/api/v1/me/activity", cookies=auth_cookies(user))
    assert resp.json()["activity"] == []
