"""Ops surface tests: extended /console/health (db/redis latency, llm budget,
recent DLQ) and the new /console/errors recent-errors tail. Both staff-gated.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
import orjson
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ERROR_RING_KEY
from app.core.redis import TXN_EVENTS_DLQ, get_redis
from app.models.enums import LlmTier
from app.models.identity import User
from app.models.tracing import LlmCall
from tests.api.conftest import auth_cookies

pytestmark = pytest.mark.anyio


async def _staff(
    make_customer: Callable[..., Any], set_staff_emails: Callable[[str], None]
) -> User:
    user, _customer = await make_customer(email="ops-staff@example.com")
    set_staff_emails("ops-staff@example.com")
    return user


async def test_health_reports_latency_budget_and_dlq(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)

    db.add(
        LlmCall(
            provider="openai", model="gpt-4.1-mini", tier=LlmTier.FAST,
            tokens_in=100, tokens_out=50, cost_usd=Decimal("0.0025"), ok=True,
            purpose="supervisor:classify", latency_ms=200,
        )
    )
    await db.commit()

    redis = get_redis()
    await redis.xadd(TXN_EVENTS_DLQ, {"data": "{}", "error": "boom one"})
    await redis.xadd(TXN_EVENTS_DLQ, {"data": "{}", "error": "boom two"})

    resp = await client.get("/api/v1/console/health", cookies=auth_cookies(staff))
    assert resp.status_code == 200
    body = resp.json()

    assert body["api"] == "ok"
    assert isinstance(body["db_latency_ms"], int | float) and body["db_latency_ms"] >= 0
    assert isinstance(body["redis_latency_ms"], int | float) and body["redis_latency_ms"] >= 0

    assert body["llm_budget"]["calls_today"] == 1
    assert Decimal(str(body["llm_budget"]["cost_usd_today"])) == Decimal("0.0025")

    dlq = body["dlq_recent"]
    assert len(dlq) == 2
    # Newest first (xrevrange): the second-added entry leads.
    assert dlq[0]["error"] == "boom two"
    assert all(entry["id"] for entry in dlq)
    assert body["worker"]["dlq"] == 2


async def test_console_errors_requires_staff(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer(email="errors-non-staff@example.com")
    resp = await client.get("/api/v1/console/errors", cookies=auth_cookies(user))
    assert resp.status_code == 403


async def test_console_errors_returns_recent_ring_newest_first(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    redis = get_redis()

    # Simulate the 500 handler's LPUSH (newest ends up at the head).
    for i in range(3):
        entry = {
            "ts": f"2026-07-05T00:00:0{i}Z",
            "request_id": f"req-{i}",
            "path": f"/api/v1/thing/{i}",
            "method": "POST",
            "status": 500,
            "error_class": "ValueError",
        }
        await redis.lpush(ERROR_RING_KEY, orjson.dumps(entry).decode())

    resp = await client.get("/api/v1/console/errors", cookies=auth_cookies(staff))
    assert resp.status_code == 200
    errors = resp.json()["errors"]
    assert [e["request_id"] for e in errors] == ["req-2", "req-1", "req-0"]
    assert errors[0]["path"] == "/api/v1/thing/2"
    assert errors[0]["status"] == 500
    assert errors[0]["error_class"] == "ValueError"


async def test_console_errors_empty_when_no_errors(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    resp = await client.get("/api/v1/console/errors", cookies=auth_cookies(staff))
    assert resp.status_code == 200
    assert resp.json() == {"errors": []}
