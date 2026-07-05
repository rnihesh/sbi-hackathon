"""Console human-handoff queue: listing, claim/resolve lifecycle, and guards.

Exercises the staff-gated queue end-to-end against the real test DB: queue
ordering (open before claimed, high urgency first), the claim 409, the resolve
note requirement and the resolver 403, customer notification on resolve, and the
live-feed publish.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import AGENT_ACTIONS, get_redis
from app.models.engagement import Notification
from app.models.enums import HandoffStatus, HandoffUrgency, NotificationKind
from app.models.handoff import HandoffRequest
from app.models.identity import User
from tests.api.conftest import auth_cookies


async def _staff(
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
    *,
    email: str = "staff-handoff@example.com",
) -> User:
    user, _customer = await make_customer(email=email)
    set_staff_emails(email)
    return user


async def _handoff(
    db: AsyncSession,
    *,
    customer_id: uuid.UUID | None = None,
    conversation_id: str = "conv-x",
    reason: str = "Wants a human",
    urgency: HandoffUrgency = HandoffUrgency.NORMAL,
    status: HandoffStatus = HandoffStatus.OPEN,
    claimed_by: str | None = None,
) -> HandoffRequest:
    row = HandoffRequest(
        customer_id=customer_id,
        conversation_id=conversation_id,
        reason=reason,
        urgency=urgency,
        status=status,
        claimed_by=claimed_by,
    )
    db.add(row)
    await db.commit()
    return row


# ---------------------------------------------------------------------------
# Staff gate + listing
# ---------------------------------------------------------------------------


async def test_handoffs_requires_staff(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    user, _ = await make_customer(email="regular@example.com")
    set_staff_emails("someone-else@example.com")
    resp = await client.get("/api/v1/console/handoffs", cookies=auth_cookies(user))
    assert resp.status_code == 403


async def test_list_handoffs_orders_open_first_high_urgency_first(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    await _handoff(db, conversation_id="low", urgency=HandoffUrgency.LOW)
    await _handoff(db, conversation_id="high", urgency=HandoffUrgency.HIGH)
    await _handoff(
        db, conversation_id="claimed", urgency=HandoffUrgency.HIGH,
        status=HandoffStatus.CLAIMED, claimed_by="a@b.com",
    )
    await _handoff(db, conversation_id="done", status=HandoffStatus.RESOLVED)

    resp = await client.get("/api/v1/console/handoffs", cookies=auth_cookies(staff))
    assert resp.status_code == 200
    body = resp.json()

    active_convs = [h["conversation_id"] for h in body["active"]]
    # Open high-urgency first, then open low-urgency, then claimed (open before claimed).
    assert active_convs == ["high", "low", "claimed"]
    resolved_convs = [h["conversation_id"] for h in body["resolved"]]
    assert resolved_convs == ["done"]


async def test_handoff_out_includes_customer_and_anon(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    _user, customer = await make_customer(email="linked@example.com", full_name="Linked Person")
    await _handoff(db, customer_id=customer.id, conversation_id="linked")
    await _handoff(db, customer_id=None, conversation_id="anon")

    resp = await client.get("/api/v1/console/handoffs", cookies=auth_cookies(staff))
    by_conv = {h["conversation_id"]: h for h in resp.json()["active"]}
    assert by_conv["linked"]["customer"]["full_name"] == "Linked Person"
    assert by_conv["anon"]["customer"] is None


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------


async def test_claim_handoff(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    row = await _handoff(db)

    resp = await client.post(
        f"/api/v1/console/handoffs/{row.id}/claim", cookies=auth_cookies(staff)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "claimed"
    assert body["claimed_by"] == "staff-handoff@example.com"
    assert body["claimed_at"] is not None

    refreshed = await db.get(HandoffRequest, row.id)
    assert refreshed is not None
    await db.refresh(refreshed)
    assert refreshed.status == HandoffStatus.CLAIMED


async def test_claim_already_claimed_returns_409(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    row = await _handoff(
        db, status=HandoffStatus.CLAIMED, claimed_by="other@example.com"
    )
    resp = await client.post(
        f"/api/v1/console/handoffs/{row.id}/claim", cookies=auth_cookies(staff)
    )
    assert resp.status_code == 409


async def test_claim_missing_returns_404(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    resp = await client.post(
        f"/api/v1/console/handoffs/{uuid.uuid4()}/claim", cookies=auth_cookies(staff)
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Resolve
# ---------------------------------------------------------------------------


async def test_resolve_requires_note(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    row = await _handoff(db, status=HandoffStatus.CLAIMED, claimed_by="staff-handoff@example.com")

    # Missing note -> 422; blank note -> 422.
    resp_missing = await client.post(
        f"/api/v1/console/handoffs/{row.id}/resolve", json={}, cookies=auth_cookies(staff)
    )
    assert resp_missing.status_code == 422
    resp_blank = await client.post(
        f"/api/v1/console/handoffs/{row.id}/resolve",
        json={"note": "   "},
        cookies=auth_cookies(staff),
    )
    assert resp_blank.status_code == 422


async def test_resolve_by_claimer_notifies_customer_and_publishes(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    _user, customer = await make_customer(email="cust@example.com")
    row = await _handoff(
        db,
        customer_id=customer.id,
        status=HandoffStatus.CLAIMED,
        claimed_by="staff-handoff@example.com",
    )

    resp = await client.post(
        f"/api/v1/console/handoffs/{row.id}/resolve",
        json={"note": "Called the customer, dispute filed."},
        cookies=auth_cookies(staff),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "resolved"
    assert body["resolution_note"] == "Called the customer, dispute filed."
    assert body["resolved_at"] is not None

    # Customer gets a system notification with the resolution note.
    note = await db.scalar(
        sa.select(Notification).where(Notification.customer_id == customer.id)
    )
    assert note is not None
    assert note.kind == NotificationKind.SYSTEM
    assert "dispute filed" in note.body

    # A handoff envelope reached the console live feed.
    entries = await get_redis().xrange(AGENT_ACTIONS)
    assert any("handoff" in payload.get("data", "") for _id, payload in entries)


async def test_resolve_unclaimed_auto_claims(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    row = await _handoff(db, status=HandoffStatus.OPEN)

    resp = await client.post(
        f"/api/v1/console/handoffs/{row.id}/resolve",
        json={"note": "Handled directly."},
        cookies=auth_cookies(staff),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "resolved"
    # Resolver becomes the claimer when the handoff was unclaimed.
    assert body["claimed_by"] == "staff-handoff@example.com"


async def test_resolve_by_non_claimer_returns_403(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    row = await _handoff(
        db, status=HandoffStatus.CLAIMED, claimed_by="someone-else@example.com"
    )
    resp = await client.post(
        f"/api/v1/console/handoffs/{row.id}/resolve",
        json={"note": "Trying to steal this."},
        cookies=auth_cookies(staff),
    )
    assert resp.status_code == 403


async def test_resolve_already_resolved_returns_409(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    row = await _handoff(
        db, status=HandoffStatus.RESOLVED, claimed_by="staff-handoff@example.com"
    )
    resp = await client.post(
        f"/api/v1/console/handoffs/{row.id}/resolve",
        json={"note": "again"},
        cookies=auth_cookies(staff),
    )
    assert resp.status_code == 409
