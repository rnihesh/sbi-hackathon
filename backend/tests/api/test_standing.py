"""Standing-instructions API: create/list/patch, ownership, and setup guards."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.banking import Account
from app.models.enums import AccountType, GoalStatus
from app.models.goal import SavingsGoal
from tests.api.conftest import auth_cookies

RUPEE = 100


async def _add_account(db: AsyncSession, customer_id: Any, balance_paise: int) -> Account:
    account = Account(
        customer_id=customer_id, type=AccountType.SAVINGS, balance_paise=balance_paise
    )
    db.add(account)
    await db.commit()
    return account


async def _add_goal(db: AsyncSession, customer_id: Any, name: str = "Trip") -> SavingsGoal:
    goal = SavingsGoal(
        customer_id=customer_id,
        name=name,
        target_paise=50_000 * RUPEE,
        baseline_paise=0,
        status=GoalStatus.ACTIVE,
    )
    db.add(goal)
    await db.commit()
    return goal


async def test_list_requires_auth(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/me/standing-instructions")
    assert resp.status_code == 401


async def test_create_and_list_with_goal_name(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    account = await _add_account(db, customer.id, 20_000 * RUPEE)
    goal = await _add_goal(db, customer.id, "New bike")

    resp = await client.post(
        "/api/v1/me/standing-instructions",
        json={
            "from_account_id": str(account.id),
            "purpose": "goal",
            "goal_id": str(goal.id),
            "amount_paise": 2_000 * RUPEE,
            "cadence": "monthly",
        },
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["purpose"] == "goal"
    assert body["goal_name"] == "New bike"
    assert body["amount_paise"] == 2_000 * RUPEE
    assert body["cadence"] == "monthly"
    assert body["status"] == "active"
    assert body["runs_count"] == 0

    listing = await client.get(
        "/api/v1/me/standing-instructions", cookies=auth_cookies(user)
    )
    assert listing.status_code == 200
    lb = listing.json()
    assert lb["active_count"] == 1
    assert lb["max_active"] == 5
    assert lb["instructions"][0]["goal_name"] == "New bike"


async def test_create_rejects_amount_over_half_balance(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    account = await _add_account(db, customer.id, 1_000 * RUPEE)

    resp = await client.post(
        "/api/v1/me/standing-instructions",
        json={
            "from_account_id": str(account.id),
            "purpose": "savings",
            "amount_paise": 600 * RUPEE,  # > 50% of 1,000
            "cadence": "weekly",
        },
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 422
    assert "50%" in resp.json()["detail"]


async def test_create_rejects_foreign_account(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer()
    _other_user, other_customer = await make_customer(email="other@example.com")
    other_account = await _add_account(db, other_customer.id, 20_000 * RUPEE)

    resp = await client.post(
        "/api/v1/me/standing-instructions",
        json={
            "from_account_id": str(other_account.id),
            "purpose": "savings",
            "amount_paise": 1_000 * RUPEE,
            "cadence": "monthly",
        },
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 422
    assert "account" in resp.json()["detail"].lower()


async def test_create_rejects_foreign_or_inactive_goal(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    account = await _add_account(db, customer.id, 20_000 * RUPEE)
    _other_user, other_customer = await make_customer(email="g@example.com")
    foreign_goal = await _add_goal(db, other_customer.id, "Not yours")

    resp = await client.post(
        "/api/v1/me/standing-instructions",
        json={
            "from_account_id": str(account.id),
            "purpose": "goal",
            "goal_id": str(foreign_goal.id),
            "amount_paise": 1_000 * RUPEE,
            "cadence": "monthly",
        },
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 422
    assert "goal" in resp.json()["detail"].lower()


async def test_create_requires_goal_for_goal_purpose(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    account = await _add_account(db, customer.id, 20_000 * RUPEE)

    resp = await client.post(
        "/api/v1/me/standing-instructions",
        json={
            "from_account_id": str(account.id),
            "purpose": "goal",
            "amount_paise": 1_000 * RUPEE,
            "cadence": "monthly",
        },
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 422


async def test_active_cap_enforced(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    account = await _add_account(db, customer.id, 100_000 * RUPEE)

    for _ in range(5):
        ok = await client.post(
            "/api/v1/me/standing-instructions",
            json={
                "from_account_id": str(account.id),
                "purpose": "savings",
                "amount_paise": 100 * RUPEE,
                "cadence": "monthly",
            },
            cookies=auth_cookies(user),
        )
        assert ok.status_code == 201

    sixth = await client.post(
        "/api/v1/me/standing-instructions",
        json={
            "from_account_id": str(account.id),
            "purpose": "savings",
            "amount_paise": 100 * RUPEE,
            "cadence": "monthly",
        },
        cookies=auth_cookies(user),
    )
    assert sixth.status_code == 409


async def test_pause_resume_cancel(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    account = await _add_account(db, customer.id, 20_000 * RUPEE)
    created = await client.post(
        "/api/v1/me/standing-instructions",
        json={
            "from_account_id": str(account.id),
            "purpose": "fd",
            "amount_paise": 1_000 * RUPEE,
            "cadence": "monthly",
        },
        cookies=auth_cookies(user),
    )
    sid = created.json()["id"]

    paused = await client.patch(
        f"/api/v1/me/standing-instructions/{sid}",
        json={"action": "pause"},
        cookies=auth_cookies(user),
    )
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"

    resumed = await client.patch(
        f"/api/v1/me/standing-instructions/{sid}",
        json={"action": "resume"},
        cookies=auth_cookies(user),
    )
    assert resumed.json()["status"] == "active"

    cancelled = await client.patch(
        f"/api/v1/me/standing-instructions/{sid}",
        json={"action": "cancel"},
        cookies=auth_cookies(user),
    )
    assert cancelled.json()["status"] == "cancelled"

    # Cancelled instructions drop out of the list.
    listing = await client.get(
        "/api/v1/me/standing-instructions", cookies=auth_cookies(user)
    )
    assert listing.json()["instructions"] == []


async def test_patch_foreign_instruction_404(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer()
    account = await _add_account(db, customer.id, 20_000 * RUPEE)
    created = await client.post(
        "/api/v1/me/standing-instructions",
        json={
            "from_account_id": str(account.id),
            "purpose": "savings",
            "amount_paise": 1_000 * RUPEE,
            "cadence": "monthly",
        },
        cookies=auth_cookies(user),
    )
    sid = created.json()["id"]

    other_user, _ = await make_customer(email="intruder@example.com")
    resp = await client.patch(
        f"/api/v1/me/standing-instructions/{sid}",
        json={"action": "cancel"},
        cookies=auth_cookies(other_user),
    )
    assert resp.status_code == 404
