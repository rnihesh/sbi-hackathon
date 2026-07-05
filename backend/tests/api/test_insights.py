"""`GET /me/insights` - shape, auth, UTC month bucketing, empty-account zeros."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.banking import Account, Transaction
from app.models.enums import AccountStatus, AccountType, TxnChannel, TxnDirection
from tests.api.conftest import auth_cookies

pytestmark = pytest.mark.anyio


async def _make_account(db: AsyncSession, customer_id: Any) -> Account:
    account = Account(
        customer_id=customer_id, type=AccountType.SAVINGS,
        balance_paise=0, status=AccountStatus.ACTIVE,
    )
    db.add(account)
    await db.flush()
    return account


def _txn(
    account_id: Any, ts: datetime, *, amount: int, direction: TxnDirection,
    category: str | None = None, merchant: str | None = None,
) -> Transaction:
    return Transaction(
        account_id=account_id, ts=ts, amount_paise=amount, direction=direction,
        channel=TxnChannel.UPI, merchant=merchant, category=category,
        balance_after_paise=0, description=None,
    )


async def test_insights_requires_auth(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/me/insights")
    assert resp.status_code == 401


async def test_insights_404_without_customer_profile(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    from app.models.identity import User

    user = User(email="no-customer-insights@example.com")
    db.add(user)
    await db.flush()
    await db.commit()

    resp = await client.get("/api/v1/me/insights", cookies=auth_cookies(user))
    assert resp.status_code == 404


async def test_insights_rejects_out_of_range_months(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer(email="badmonths@example.com")
    resp = await client.get(
        "/api/v1/me/insights", params={"months": 13}, cookies=auth_cookies(user)
    )
    assert resp.status_code == 422

    resp = await client.get(
        "/api/v1/me/insights", params={"months": 0}, cookies=auth_cookies(user)
    )
    assert resp.status_code == 422


async def test_insights_empty_account_returns_honest_zeros(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer(email="emptyacct@example.com")

    resp = await client.get(
        "/api/v1/me/insights", params={"months": 3}, cookies=auth_cookies(user)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["months"]) == 3
    for month in body["months"]:
        assert month["total_in_paise"] == 0
        assert month["total_out_paise"] == 0
        assert month["by_category"] == []
    assert body["note"] is None
    assert body["trends"] == {
        "top_category_change": None,
        "largest_txn_30d": None,
        "recurring": [],
    }


async def test_insights_shape_and_month_bucketing_across_utc_boundary(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer(email="insightsshape@example.com")
    account = await _make_account(db, customer.id)

    now = datetime.now(UTC)
    current_month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    just_before = current_month_start - timedelta(seconds=1)  # last second of prior month

    db.add_all(
        [
            _txn(account.id, now, amount=50_000_00, direction=TxnDirection.CREDIT,
                 category="salary", merchant="Employer Inc"),
            _txn(account.id, now, amount=1_200_00, direction=TxnDirection.DEBIT,
                 category="groceries", merchant="BigBasket"),
            _txn(account.id, now, amount=800_00, direction=TxnDirection.DEBIT,
                 category="groceries", merchant="BigBasket"),
            _txn(account.id, now, amount=600_00, direction=TxnDirection.DEBIT,
                 category="transport", merchant="Ola"),
            # Lands in the PREVIOUS month's bucket despite being "close" to now.
            _txn(account.id, just_before, amount=2_000_00, direction=TxnDirection.DEBIT,
                 category="shopping", merchant="Amazon"),
        ]
    )
    await db.commit()

    resp = await client.get(
        "/api/v1/me/insights", params={"months": 2}, cookies=auth_cookies(user)
    )
    assert resp.status_code == 200
    body = resp.json()

    assert [m["month"] for m in body["months"]] == [
        f"{now.year:04d}-{now.month:02d}",
        f"{just_before.year:04d}-{just_before.month:02d}",
    ]

    current, previous = body["months"]
    assert current["total_in_paise"] == 50_000_00
    assert current["total_out_paise"] == 2_600_00
    by_category = {c["category"]: c for c in current["by_category"]}
    assert by_category["groceries"]["amount_paise"] == 2_000_00
    assert by_category["groceries"]["txn_count"] == 2
    assert by_category["groceries"]["share_pct"] == pytest.approx(76.9, abs=0.1)
    assert by_category["transport"]["amount_paise"] == 600_00

    assert previous["total_out_paise"] == 2_000_00
    assert previous["by_category"][0]["category"] == "shopping"

    # Trends: largest txn in 30d, top mover between the two months, no recurring
    # merchant yet (a single occurrence each).
    assert body["trends"]["largest_txn_30d"]["merchant"] in {"Amazon", "BigBasket"}
    assert body["trends"]["recurring"] == []
    assert body["trends"]["top_category_change"] is not None
