"""Memory-transparency API: view + forget what Sarathi remembers.

Covers the happy paths plus the privacy-critical isolation guarantees:
cross-tenant reads and deletes must 404/no-op, never leak or destroy another
customer's memories.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import MemoryKind
from app.models.identity import User
from app.models.memory import AgentMemory
from tests.api.conftest import auth_cookies


def _mem(customer_id: uuid.UUID, text: str, kind: MemoryKind = MemoryKind.EPISODIC) -> AgentMemory:
    return AgentMemory(customer_id=customer_id, kind=kind, text=text, embedding=None)


# ---------------------------------------------------------------------------
# GET /me/memory
# ---------------------------------------------------------------------------


async def test_get_memory_requires_auth(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/me/memory")
    assert resp.status_code == 401


async def test_get_memory_404_without_customer_profile(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    user = User(email="no-customer@example.com")
    db.add(user)
    await db.commit()

    resp = await client.get("/api/v1/me/memory", cookies=auth_cookies(user))
    assert resp.status_code == 404


async def test_get_memory_newest_first_with_kinds(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    db.add(_mem(customer.id, "first", kind=MemoryKind.EPISODIC))
    await db.commit()  # separate txn so created_at strictly precedes the next
    db.add(_mem(customer.id, "second", kind=MemoryKind.FACT))
    await db.commit()

    resp = await client.get("/api/v1/me/memory", cookies=auth_cookies(user))
    assert resp.status_code == 200
    memories = resp.json()["memories"]
    assert [m["text"] for m in memories] == ["second", "first"]
    assert {m["kind"] for m in memories} == {"fact", "episodic"}


async def test_get_memory_includes_profile_facts(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer(full_name="Asha Rao", city="Pune")

    resp = await client.get("/api/v1/me/memory", cookies=auth_cookies(user))
    assert resp.status_code == 200
    facts = resp.json()["profile_facts"]
    assert facts["exists"] is True
    assert facts["name"] == "Asha Rao"
    assert facts["city"] == "Pune"


async def test_get_memory_only_returns_own(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer(email="me@example.com")
    _other, other_customer = await make_customer(email="other@example.com")
    db.add(_mem(customer.id, "mine"))
    db.add(_mem(other_customer.id, "theirs"))
    await db.commit()

    resp = await client.get("/api/v1/me/memory", cookies=auth_cookies(user))
    assert resp.status_code == 200
    assert [m["text"] for m in resp.json()["memories"]] == ["mine"]


async def test_get_memory_caps_at_100(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    db.add_all([_mem(customer.id, f"m{i}") for i in range(105)])
    await db.commit()

    resp = await client.get("/api/v1/me/memory", cookies=auth_cookies(user))
    assert resp.status_code == 200
    assert len(resp.json()["memories"]) == 100


# ---------------------------------------------------------------------------
# DELETE /me/memory/{id}
# ---------------------------------------------------------------------------


async def test_forget_one_memory(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    m = _mem(customer.id, "likes systematic plans", kind=MemoryKind.PREFERENCE)
    db.add(m)
    await db.commit()
    mid = str(m.id)

    resp = await client.delete(f"/api/v1/me/memory/{mid}", cookies=auth_cookies(user))
    assert resp.status_code == 204

    remaining = await client.get("/api/v1/me/memory", cookies=auth_cookies(user))
    assert all(item["id"] != mid for item in remaining.json()["memories"])


async def test_forget_one_requires_auth(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    _user, customer = await make_customer()
    m = _mem(customer.id, "x")
    db.add(m)
    await db.commit()

    resp = await client.delete(f"/api/v1/me/memory/{m.id}")
    assert resp.status_code == 401


async def test_forget_missing_memory_404(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer()
    resp = await client.delete(
        f"/api/v1/me/memory/{uuid.uuid4()}", cookies=auth_cookies(user)
    )
    assert resp.status_code == 404


async def test_forget_other_customers_memory_404(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    owner, owner_customer = await make_customer(email="owner@example.com")
    intruder, _ = await make_customer(email="intruder@example.com")
    m = _mem(owner_customer.id, "owner's secret")
    db.add(m)
    await db.commit()
    mid = str(m.id)

    # Intruder cannot reach it: indistinguishable from "does not exist".
    resp = await client.delete(f"/api/v1/me/memory/{mid}", cookies=auth_cookies(intruder))
    assert resp.status_code == 404

    # And it is still there for the owner.
    owner_view = await client.get("/api/v1/me/memory", cookies=auth_cookies(owner))
    assert any(item["id"] == mid for item in owner_view.json()["memories"])


# ---------------------------------------------------------------------------
# DELETE /me/memory (forget everything)
# ---------------------------------------------------------------------------


async def test_forget_all_requires_auth(client: httpx.AsyncClient) -> None:
    resp = await client.delete("/api/v1/me/memory")
    assert resp.status_code == 401


async def test_forget_all_only_deletes_own(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer(email="me@example.com")
    other, other_customer = await make_customer(email="other@example.com")
    db.add_all([_mem(customer.id, "a"), _mem(customer.id, "b"), _mem(customer.id, "c")])
    db.add(_mem(other_customer.id, "theirs"))
    await db.commit()

    resp = await client.delete("/api/v1/me/memory", cookies=auth_cookies(user))
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 3

    # Mine are gone...
    mine = await client.get("/api/v1/me/memory", cookies=auth_cookies(user))
    assert mine.json()["memories"] == []
    # ...and the other customer's are untouched.
    theirs = await client.get("/api/v1/me/memory", cookies=auth_cookies(other))
    assert [m["text"] for m in theirs.json()["memories"]] == ["theirs"]


async def test_forget_all_on_empty_returns_zero(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer()
    resp = await client.delete("/api/v1/me/memory", cookies=auth_cookies(user))
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 0
