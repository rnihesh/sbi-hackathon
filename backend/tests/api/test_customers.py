"""Customer-facing `/me/dashboard` tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.banking import Account, Transaction
from app.models.catalog import Holding, Product
from app.models.engagement import Nudge
from app.models.enums import (
    AccountStatus,
    AccountType,
    HoldingStatus,
    NudgeStatus,
    TxnChannel,
    TxnDirection,
)
from tests.api.conftest import auth_cookies


async def test_dashboard_requires_auth(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/me/dashboard")
    assert resp.status_code == 401


async def test_dashboard_returns_accounts_txns_holdings_nudges(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer(full_name="Dashboard User")

    account = Account(
        customer_id=customer.id, type=AccountType.SAVINGS,
        balance_paise=50_000_00, status=AccountStatus.ACTIVE,
    )
    db.add(account)
    await db.flush()

    for i in range(3):
        db.add(
            Transaction(
                account_id=account.id,
                ts=datetime.now(UTC),
                amount_paise=1000_00 + i,
                direction=TxnDirection.DEBIT,
                channel=TxnChannel.UPI,
                merchant="Test Merchant",
                category="groceries",
                balance_after_paise=50_000_00 - (1000_00 + i),
                description="test",
            )
        )

    product = Product(code="test_savings_dash", name="Test Savings", category="deposit")
    db.add(product)
    await db.flush()
    db.add(Holding(customer_id=customer.id, product_id=product.id, status=HoldingStatus.ACTIVE))

    db.add(Nudge(customer_id=customer.id, title="Try UPI", body="Body", status=NudgeStatus.SENT))
    await db.commit()

    resp = await client.get("/api/v1/me/dashboard", cookies=auth_cookies(user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["customer"]["id"] == str(customer.id)
    assert len(body["accounts"]) == 1
    assert body["accounts"][0]["balance_paise"] == 50_000_00
    assert len(body["recent_transactions"]) == 3
    assert len(body["holdings"]) == 1
    assert body["holdings"][0]["product"]["code"] == "test_savings_dash"
    assert body["unseen_nudges"] == 1


async def test_dashboard_404_without_customer_profile(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    from app.models.identity import User

    user = User(email="no-customer@example.com")
    db.add(user)
    await db.flush()
    await db.commit()

    resp = await client.get("/api/v1/me/dashboard", cookies=auth_cookies(user))
    assert resp.status_code == 404
