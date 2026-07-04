"""Tests for POST /me/demo-activity and GET /chat/sessions (history list)."""

from __future__ import annotations

import httpx
import orjson
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.banking import Account, Transaction
from app.models.conversation import Conversation, Message
from app.models.engagement import Notification
from app.models.enums import NotificationKind
from app.services.products import seed_catalog
from tests.agents.conftest import FakeRouter, ScriptedHandler, make_response

from .conftest import auth_cookies

pytestmark = pytest.mark.anyio

_FLAVOR = {
    "employer_name": "Bengaluru Textiles Pvt Ltd",
    "merchant_flavor": [
        "Nandini Milk Booth",
        "MTR Restaurant",
        "Namma Metro",
        "Apollo Pharmacy Koramangala",
        "Third Wave Coffee",
        "More Supermarket Indiranagar",
    ],
    "spending_note": "Steady urban spender with frequent food-delivery and metro use.",
}


def _flavor_router() -> FakeRouter:
    """Fake router that returns valid persona-flavour JSON (no network)."""
    handler = ScriptedHandler(
        queues={"demo:persona_flavor": [make_response(orjson.dumps(_FLAVOR).decode())]},
        default_text="{}",
    )
    return FakeRouter(handler)


async def test_demo_activity_requires_auth(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/me/demo-activity")
    assert resp.status_code == 401


async def test_demo_activity_fills_account_then_409(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.demo as demo_module

    monkeypatch.setattr(demo_module, "get_router", _flavor_router)
    await seed_catalog(db)
    await db.commit()
    user, customer = await make_customer()

    resp = await client.post("/api/v1/me/demo-activity", cookies=auth_cookies(user))
    assert resp.status_code == 200
    body = resp.json()
    # 6 months of realistic activity; even the sparsest archetype (retiree)
    # clears this floor, keeping the test stable across random customer ids.
    assert body["transactions"] > 20
    assert body["months"] == 6
    assert body["balance_paise"] >= 0

    txn_count = await db.scalar(
        select(func.count())
        .select_from(Transaction)
        .join(Account, Account.id == Transaction.account_id)
        .where(Account.customer_id == customer.id)
    )
    assert int(txn_count or 0) == body["transactions"]

    # Demo readiness is a real customer moment - a system notification lands.
    note = (
        await db.execute(
            select(Notification).where(Notification.customer_id == customer.id)
        )
    ).scalar_one()
    assert note.kind is NotificationKind.SYSTEM
    assert note.title == "Your demo activity is ready"
    assert note.read is False

    # Profile isolation: demo activity must NOT overwrite the real identity
    # columns - only the persona JSON and digital maturity are set.
    await db.refresh(customer)
    assert customer.city is None
    assert customer.occupation is None
    assert customer.segment is None
    assert customer.annual_income_paise is None
    assert customer.persona.get("demo_loaded") is True
    assert isinstance(customer.persona.get("demo_salt"), int)
    assert customer.persona.get("demo_flavor", {}).get("merchant_flavor") == _FLAVOR[
        "merchant_flavor"
    ]

    # Guarded: a second call must refuse (activity already loaded).
    again = await client.post("/api/v1/me/demo-activity", cookies=auth_cookies(user))
    assert again.status_code == 409


async def test_demo_activity_cleans_legacy_identity_pollution_on_409(
    client: httpx.AsyncClient, db: AsyncSession, make_customer
) -> None:
    """A customer polluted by an older demo version gets healed even when the
    activity guard (409) short-circuits the reload."""
    from datetime import UTC, datetime

    from app.models.enums import AccountType, TxnChannel, TxnDirection
    from app.sim.personas import Archetype

    user, customer = await make_customer()
    # Simulate the OLD behaviour: identity columns overwritten to persona values.
    customer.persona = {
        "archetype": Archetype.YOUNG_SALARIED_TECHIE.value,
        "city": "Pune",
        "occupation": "Software Engineer",
        "monthly_income_paise": 100_000 * 100,
    }
    customer.city = "Pune"
    customer.occupation = "Software Engineer"
    customer.segment = "salaried"
    customer.annual_income_paise = 100_000 * 100 * 12
    account = Account(
        customer_id=customer.id, type=AccountType.SAVINGS, balance_paise=0, label="s"
    )
    db.add(account)
    await db.flush()
    db.add_all(
        [
            Transaction(
                account_id=account.id,
                ts=datetime.now(UTC),
                amount_paise=100,
                direction=TxnDirection.DEBIT,
                channel=TxnChannel.UPI,
                merchant="M",
                category="groceries",
                balance_after_paise=0,
            )
            for _ in range(25)  # over the already-loaded threshold -> 409
        ]
    )
    await db.commit()

    resp = await client.post("/api/v1/me/demo-activity", cookies=auth_cookies(user))
    assert resp.status_code == 409

    # The polluted identity columns are nulled despite the 409 short-circuit.
    await db.refresh(customer)
    assert customer.city is None
    assert customer.occupation is None
    assert customer.segment is None
    assert customer.annual_income_paise is None


async def test_chat_sessions_list_empty_for_fresh_customer(
    client: httpx.AsyncClient, make_customer
) -> None:
    user, _ = await make_customer()
    resp = await client.get("/api/v1/chat/sessions", cookies=auth_cookies(user))
    assert resp.status_code == 200
    assert resp.json() == {"sessions": []}


async def test_chat_sessions_list_returns_titled_history(
    client: httpx.AsyncClient, db: AsyncSession, make_customer
) -> None:
    user, customer = await make_customer()
    conv = Conversation(customer_id=customer.id)
    db.add(conv)
    await db.flush()
    db.add_all(
        [
            Message(conversation_id=conv.id, role="user", content="I want a savings account"),
            Message(conversation_id=conv.id, role="assistant", content="Happy to help."),
        ]
    )
    empty_conv = Conversation(customer_id=customer.id)
    db.add(empty_conv)
    await db.commit()

    resp = await client.get("/api/v1/chat/sessions", cookies=auth_cookies(user))
    assert resp.status_code == 200
    sessions = resp.json()["sessions"]
    # The never-used thread is filtered out.
    assert len(sessions) == 1
    assert sessions[0]["conversation_id"] == str(conv.id)
    assert sessions[0]["title"] == "I want a savings account"
    assert sessions[0]["message_count"] == 2


async def test_chat_sessions_list_anonymous_is_empty(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/chat/sessions")
    assert resp.status_code == 200
    assert resp.json() == {"sessions": []}
