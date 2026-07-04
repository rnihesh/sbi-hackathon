"""Customer nudge inbox tests: listing, ownership, and status transitions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.engagement import Nudge
from app.models.enums import NudgeStatus
from tests.api.conftest import auth_cookies


async def test_list_nudges_requires_auth(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/me/nudges")
    assert resp.status_code == 401


async def test_list_nudges_newest_first(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    n1 = Nudge(customer_id=customer.id, title="First", body="b1", status=NudgeStatus.SENT)
    db.add(n1)
    await db.commit()  # separate transaction so `created_at` strictly precedes n2's
    n2 = Nudge(customer_id=customer.id, title="Second", body="b2", status=NudgeStatus.SENT)
    db.add(n2)
    await db.commit()

    resp = await client.get("/api/v1/me/nudges", cookies=auth_cookies(user))
    assert resp.status_code == 200
    titles = [n["title"] for n in resp.json()["nudges"]]
    assert titles[0] == "Second"
    assert titles[1] == "First"


async def test_act_on_nudge_updates_status(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    nudge = Nudge(customer_id=customer.id, title="Try FD", body="body", status=NudgeStatus.SENT)
    db.add(nudge)
    await db.commit()

    resp = await client.post(
        f"/api/v1/me/nudges/{nudge.id}/act",
        json={"action": "acted"},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "acted"


async def test_act_on_nudge_enforces_ownership(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    owner, owner_customer = await make_customer(email="owner2@example.com")
    other, _other_customer = await make_customer(email="other2@example.com")
    nudge = Nudge(
        customer_id=owner_customer.id, title="Owner's nudge", body="b", status=NudgeStatus.SENT
    )
    db.add(nudge)
    await db.commit()

    resp = await client.post(
        f"/api/v1/me/nudges/{nudge.id}/act",
        json={"action": "seen"},
        cookies=auth_cookies(other),
    )
    assert resp.status_code == 403

    ok_resp = await client.post(
        f"/api/v1/me/nudges/{nudge.id}/act",
        json={"action": "seen"},
        cookies=auth_cookies(owner),
    )
    assert ok_resp.status_code == 200
    assert ok_resp.json()["status"] == "seen"


async def test_act_on_unknown_nudge_404(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    import uuid

    user, _customer = await make_customer()
    resp = await client.post(
        f"/api/v1/me/nudges/{uuid.uuid4()}/act",
        json={"action": "seen"},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 404
