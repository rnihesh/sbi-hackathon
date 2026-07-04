"""Customer notification inbox tests: listing, unread counts, read, ownership."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.engagement import Notification
from app.models.enums import NotificationKind
from tests.api.conftest import auth_cookies


def _notif(customer_id: uuid.UUID, title: str, **kw: Any) -> Notification:
    return Notification(
        customer_id=customer_id,
        kind=kw.pop("kind", NotificationKind.SYSTEM),
        title=title,
        body=kw.pop("body", "body"),
        link=kw.pop("link", None),
        read=kw.pop("read", False),
    )


async def test_list_notifications_requires_auth(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/me/notifications")
    assert resp.status_code == 401


async def test_list_newest_first_with_unread_count(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    db.add(_notif(customer.id, "First", kind=NotificationKind.ACCOUNT))
    await db.commit()  # separate txn so created_at strictly precedes the next
    db.add(_notif(customer.id, "Second", kind=NotificationKind.OFFER, read=True))
    await db.commit()

    resp = await client.get("/api/v1/me/notifications", cookies=auth_cookies(user))
    assert resp.status_code == 200
    payload = resp.json()
    titles = [n["title"] for n in payload["notifications"]]
    assert titles == ["Second", "First"]
    # Only "First" is unread.
    assert payload["unread"] == 1


async def test_list_respects_limit(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    for i in range(5):
        db.add(_notif(customer.id, f"n{i}"))
    await db.commit()

    resp = await client.get(
        "/api/v1/me/notifications", params={"limit": 2}, cookies=auth_cookies(user)
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert len(payload["notifications"]) == 2
    # unread reflects all rows, not just the page.
    assert payload["unread"] == 5


async def test_list_only_returns_own(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer(email="me@example.com")
    _other, other_customer = await make_customer(email="other@example.com")
    db.add(_notif(customer.id, "Mine"))
    db.add(_notif(other_customer.id, "Theirs"))
    await db.commit()

    resp = await client.get("/api/v1/me/notifications", cookies=auth_cookies(user))
    assert resp.status_code == 200
    titles = [n["title"] for n in resp.json()["notifications"]]
    assert titles == ["Mine"]


async def test_mark_specific_ids_read(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    n1 = _notif(customer.id, "one")
    n2 = _notif(customer.id, "two")
    db.add_all([n1, n2])
    await db.commit()
    n1_id = str(n1.id)

    resp = await client.post(
        "/api/v1/me/notifications/read", json={"ids": [n1_id]}, cookies=auth_cookies(user)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["marked"] == 1
    assert body["unread"] == 1  # n2 still unread


async def test_mark_all_read(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    db.add_all([_notif(customer.id, "a"), _notif(customer.id, "b"), _notif(customer.id, "c")])
    await db.commit()

    resp = await client.post(
        "/api/v1/me/notifications/read", json={"all": True}, cookies=auth_cookies(user)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["marked"] == 3
    assert body["unread"] == 0


async def test_mark_read_noop_without_ids_or_all(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    db.add(_notif(customer.id, "a"))
    await db.commit()

    resp = await client.post(
        "/api/v1/me/notifications/read", json={}, cookies=auth_cookies(user)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["marked"] == 0
    assert body["unread"] == 1


async def test_mark_read_enforces_ownership(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    owner, owner_customer = await make_customer(email="owner@example.com")
    other, _ = await make_customer(email="intruder@example.com")
    n = _notif(owner_customer.id, "owner's")
    db.add(n)
    await db.commit()
    n_id = str(n.id)

    # Intruder targeting the owner's notification marks nothing (WHERE scopes to
    # the caller's own rows).
    resp = await client.post(
        "/api/v1/me/notifications/read", json={"ids": [n_id]}, cookies=auth_cookies(other)
    )
    assert resp.status_code == 200
    assert resp.json()["marked"] == 0

    # And it is still unread for the owner.
    owner_resp = await client.get("/api/v1/me/notifications", cookies=auth_cookies(owner))
    assert owner_resp.json()["unread"] == 1
