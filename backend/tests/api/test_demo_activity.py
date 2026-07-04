"""Tests for POST /me/demo-activity and GET /chat/sessions (history list)."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.banking import Account, Transaction
from app.models.conversation import Conversation, Message
from app.services.products import seed_catalog

from .conftest import auth_cookies

pytestmark = pytest.mark.anyio


async def test_demo_activity_requires_auth(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/me/demo-activity")
    assert resp.status_code == 401


async def test_demo_activity_fills_account_then_409(
    client: httpx.AsyncClient, db: AsyncSession, make_customer
) -> None:
    await seed_catalog(db)
    await db.commit()
    user, customer = await make_customer()

    resp = await client.post("/api/v1/me/demo-activity", cookies=auth_cookies(user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["transactions"] > 100  # 6 months of realistic activity
    assert body["months"] == 6
    assert body["balance_paise"] >= 0

    txn_count = await db.scalar(
        select(func.count())
        .select_from(Transaction)
        .join(Account, Account.id == Transaction.account_id)
        .where(Account.customer_id == customer.id)
    )
    assert int(txn_count or 0) == body["transactions"]

    # Deterministic per customer AND guarded: a second call must refuse.
    again = await client.post("/api/v1/me/demo-activity", cookies=auth_cookies(user))
    assert again.status_code == 409


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
