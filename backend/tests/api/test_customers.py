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


# ---------------------------------------------------------------------------
# PATCH /me/preferences (vernacular chat language)
# ---------------------------------------------------------------------------


async def test_preferences_requires_auth(client: httpx.AsyncClient) -> None:
    resp = await client.patch("/api/v1/me/preferences", json={"preferred_language": "hindi"})
    assert resp.status_code == 401


async def test_preferences_sets_preferred_language(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer(full_name="Lang User")
    assert customer.preferred_language is None

    resp = await client.patch(
        "/api/v1/me/preferences",
        json={"preferred_language": "hindi"},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 200
    assert resp.json()["preferred_language"] == "hindi"

    me_resp = await client.get("/api/v1/me", cookies=auth_cookies(user))
    assert me_resp.json()["customer"]["preferred_language"] == "hindi"


async def test_preferences_accepts_every_supported_language(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    from app.agents.language import SUPPORTED_LANGUAGES

    user, _customer = await make_customer(full_name="All Langs User")
    for language in SUPPORTED_LANGUAGES:
        resp = await client.patch(
            "/api/v1/me/preferences",
            json={"preferred_language": language},
            cookies=auth_cookies(user),
        )
        assert resp.status_code == 200, language
        assert resp.json()["preferred_language"] == language


async def test_preferences_null_clears_to_auto(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer(full_name="Auto User", preferred_language="tamil")

    resp = await client.patch(
        "/api/v1/me/preferences",
        json={"preferred_language": None},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 200
    assert resp.json()["preferred_language"] is None


async def test_preferences_rejects_unsupported_language(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer(full_name="Bad Lang User")

    resp = await client.patch(
        "/api/v1/me/preferences",
        json={"preferred_language": "klingon"},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 422


async def test_preferences_404_without_customer_profile(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    from app.models.identity import User

    user = User(email="no-customer-prefs@example.com")
    db.add(user)
    await db.flush()
    await db.commit()

    resp = await client.patch(
        "/api/v1/me/preferences",
        json={"preferred_language": "hindi"},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /me/preferences (profile fields: full_name, phone, city)
# ---------------------------------------------------------------------------


async def test_preferences_updates_full_name(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer(full_name="Old Name")

    resp = await client.patch(
        "/api/v1/me/preferences",
        json={"full_name": "  New Name  "},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "New Name"


async def test_preferences_rejects_short_full_name(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer(full_name="Old Name")

    resp = await client.patch(
        "/api/v1/me/preferences",
        json={"full_name": "A"},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 422


async def test_preferences_rejects_full_name_too_long(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer(full_name="Old Name")

    resp = await client.patch(
        "/api/v1/me/preferences",
        json={"full_name": "A" * 81},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 422


async def test_preferences_rejects_null_full_name(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer(full_name="Old Name")

    resp = await client.patch(
        "/api/v1/me/preferences",
        json={"full_name": None},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 422


async def test_preferences_updates_phone(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, customer = await make_customer(full_name="Phone User")
    assert customer.phone is None

    resp = await client.patch(
        "/api/v1/me/preferences",
        json={"phone": "9876543210"},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 200
    assert resp.json()["phone"] == "9876543210"


async def test_preferences_accepts_phone_with_country_code(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer(full_name="Phone User 2")

    resp = await client.patch(
        "/api/v1/me/preferences",
        json={"phone": "+91-9876543210"},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 200
    assert resp.json()["phone"] == "+91-9876543210"


async def test_preferences_rejects_invalid_phone(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer(full_name="Phone User 3")

    resp = await client.patch(
        "/api/v1/me/preferences",
        json={"phone": "12345"},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 422


async def test_preferences_clears_phone_with_null(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer(full_name="Phone User 4", phone="9876543210")

    resp = await client.patch(
        "/api/v1/me/preferences",
        json={"phone": None},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 200
    assert resp.json()["phone"] is None


async def test_preferences_updates_city(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer(full_name="City User")

    resp = await client.patch(
        "/api/v1/me/preferences",
        json={"city": "  Pune  "},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 200
    assert resp.json()["city"] == "Pune"


async def test_preferences_rejects_short_city(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer(full_name="City User 2")

    resp = await client.patch(
        "/api/v1/me/preferences",
        json={"city": "P"},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 422


async def test_preferences_clears_city_with_null(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer(full_name="City User 3", city="Mumbai")

    resp = await client.patch(
        "/api/v1/me/preferences",
        json={"city": None},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 200
    assert resp.json()["city"] is None


async def test_preferences_partial_update_only_touches_provided_fields(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer(
        full_name="Partial User", phone="9876543210", city="Chennai", preferred_language="tamil"
    )

    resp = await client.patch(
        "/api/v1/me/preferences",
        json={"city": "Bengaluru"},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["city"] == "Bengaluru"
    # Untouched fields survive the partial update unchanged.
    assert body["full_name"] == "Partial User"
    assert body["phone"] == "9876543210"
    assert body["preferred_language"] == "tamil"


async def test_preferences_updates_multiple_fields_at_once(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer(full_name="Multi User")

    resp = await client.patch(
        "/api/v1/me/preferences",
        json={"full_name": "Multi Updated", "phone": "9123456780", "city": "Delhi"},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["full_name"] == "Multi Updated"
    assert body["phone"] == "9123456780"
    assert body["city"] == "Delhi"
