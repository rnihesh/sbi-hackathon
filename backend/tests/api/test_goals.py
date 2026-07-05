"""Savings-goals API: create/list/progress, achievement flip, cap, patch, delete, ownership."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.banking import Account
from app.models.enums import AccountType
from tests.api.conftest import auth_cookies

RUPEE = 100  # paise per rupee


async def _add_account(db: AsyncSession, customer_id: Any, balance_paise: int) -> None:
    """Give a customer a savings account with a set balance (its own committed txn)."""
    db.add(Account(customer_id=customer_id, type=AccountType.SAVINGS, balance_paise=balance_paise))
    await db.commit()


async def test_list_requires_auth(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/me/goals")
    assert resp.status_code == 401


async def test_create_captures_baseline_and_lists(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    await _add_account(db, customer.id, 100 * RUPEE)  # opening balance ₹100

    resp = await client.post(
        "/api/v1/me/goals",
        json={"name": "New bike", "target_paise": 50_000 * RUPEE},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "New bike"
    assert body["baseline_paise"] == 100 * RUPEE
    assert body["progress_paise"] == 0  # no growth yet
    assert body["pct"] == 0.0
    assert body["status"] == "active"

    listing = await client.get("/api/v1/me/goals", cookies=auth_cookies(user))
    assert listing.status_code == 200
    lb = listing.json()
    assert lb["active_count"] == 1
    assert lb["max_active"] == 5
    assert [g["name"] for g in lb["goals"]] == ["New bike"]


async def test_progress_reflects_balance_growth(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    await _add_account(db, customer.id, 10_000 * RUPEE)

    await client.post(
        "/api/v1/me/goals",
        json={"name": "Trip", "target_paise": 5_000 * RUPEE},
        cookies=auth_cookies(user),
    )
    # Balance grows by ₹2,500 after the goal was set -> 50% of a ₹5,000 target.
    await _add_account(db, customer.id, 2_500 * RUPEE)

    g = (await client.get("/api/v1/me/goals", cookies=auth_cookies(user))).json()["goals"][0]
    assert g["progress_paise"] == 2_500 * RUPEE
    assert g["pct"] == 50.0
    assert g["status"] == "active"


async def test_goal_achieved_flips_and_notifies_once(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    await _add_account(db, customer.id, 1_000 * RUPEE)

    await client.post(
        "/api/v1/me/goals",
        json={"name": "Emergency fund", "target_paise": 2_000 * RUPEE},
        cookies=auth_cookies(user),
    )
    # Grow balance past baseline + target.
    await _add_account(db, customer.id, 2_500 * RUPEE)

    g = (await client.get("/api/v1/me/goals", cookies=auth_cookies(user))).json()["goals"][0]
    assert g["status"] == "achieved"
    assert g["pct"] == 100.0

    notifs = (await client.get("/api/v1/me/notifications", cookies=auth_cookies(user))).json()
    achieved = [n for n in notifs["notifications"] if n["title"] == "Goal achieved!"]
    assert len(achieved) == 1

    # Reading again must not re-notify (idempotent lazy evaluation).
    await client.get("/api/v1/me/goals", cookies=auth_cookies(user))
    notifs2 = (await client.get("/api/v1/me/notifications", cookies=auth_cookies(user))).json()
    assert sum(1 for n in notifs2["notifications"] if n["title"] == "Goal achieved!") == 1


async def test_active_goal_cap_returns_409(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer()
    for i in range(5):
        r = await client.post(
            "/api/v1/me/goals",
            json={"name": f"Goal {i}", "target_paise": 1_000 * RUPEE},
            cookies=auth_cookies(user),
        )
        assert r.status_code == 201
    sixth = await client.post(
        "/api/v1/me/goals",
        json={"name": "Sixth", "target_paise": 1_000 * RUPEE},
        cookies=auth_cookies(user),
    )
    assert sixth.status_code == 409


async def test_create_rejects_nonpositive_target(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer()
    resp = await client.post(
        "/api/v1/me/goals",
        json={"name": "Bad", "target_paise": 0},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 422


async def test_archive_hides_goal_and_frees_a_slot(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer()
    ids = []
    for i in range(5):
        r = await client.post(
            "/api/v1/me/goals",
            json={"name": f"Goal {i}", "target_paise": 1_000 * RUPEE},
            cookies=auth_cookies(user),
        )
        ids.append(r.json()["id"])

    patch = await client.patch(
        f"/api/v1/me/goals/{ids[0]}", json={"status": "archived"}, cookies=auth_cookies(user)
    )
    assert patch.status_code == 200
    assert patch.json()["status"] == "archived"

    listing = (await client.get("/api/v1/me/goals", cookies=auth_cookies(user))).json()
    assert listing["active_count"] == 4
    assert ids[0] not in [g["id"] for g in listing["goals"]]  # archived hidden

    # Archiving freed a slot, so a new goal is allowed again.
    again = await client.post(
        "/api/v1/me/goals",
        json={"name": "Replacement", "target_paise": 1_000 * RUPEE},
        cookies=auth_cookies(user),
    )
    assert again.status_code == 201


async def test_patch_rejects_non_archived_status(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer()
    gid = (
        await client.post(
            "/api/v1/me/goals",
            json={"name": "Fund", "target_paise": 1_000 * RUPEE},
            cookies=auth_cookies(user),
        )
    ).json()["id"]
    resp = await client.patch(
        f"/api/v1/me/goals/{gid}", json={"status": "active"}, cookies=auth_cookies(user)
    )
    assert resp.status_code == 422


async def test_patch_updates_name_and_date(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer()
    gid = (
        await client.post(
            "/api/v1/me/goals",
            json={"name": "Fund", "target_paise": 1_000 * RUPEE},
            cookies=auth_cookies(user),
        )
    ).json()["id"]
    resp = await client.patch(
        f"/api/v1/me/goals/{gid}",
        json={"name": "Renamed fund", "target_date": "2026-12-31"},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Renamed fund"
    assert body["target_date"] == "2026-12-31"


async def test_delete_goal(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer()
    gid = (
        await client.post(
            "/api/v1/me/goals",
            json={"name": "Fund", "target_paise": 1_000 * RUPEE},
            cookies=auth_cookies(user),
        )
    ).json()["id"]
    deleted = await client.delete(f"/api/v1/me/goals/{gid}", cookies=auth_cookies(user))
    assert deleted.status_code == 204
    listing = (await client.get("/api/v1/me/goals", cookies=auth_cookies(user))).json()
    assert listing["goals"] == []


async def test_patch_and_delete_enforce_ownership(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    owner, _oc = await make_customer(email="owner@example.com")
    intruder, _ic = await make_customer(email="intruder@example.com")
    gid = (
        await client.post(
            "/api/v1/me/goals",
            json={"name": "Mine", "target_paise": 1_000 * RUPEE},
            cookies=auth_cookies(owner),
        )
    ).json()["id"]

    p = await client.patch(
        f"/api/v1/me/goals/{gid}", json={"name": "Hijack"}, cookies=auth_cookies(intruder)
    )
    assert p.status_code == 404
    d = await client.delete(f"/api/v1/me/goals/{gid}", cookies=auth_cookies(intruder))
    assert d.status_code == 404

    # Intruder's own list is empty; owner's goal is untouched.
    intruder_list = (await client.get("/api/v1/me/goals", cookies=auth_cookies(intruder))).json()
    assert intruder_list["goals"] == []
    owner_list = (await client.get("/api/v1/me/goals", cookies=auth_cookies(owner))).json()
    assert owner_list["goals"][0]["name"] == "Mine"
