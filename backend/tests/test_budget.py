"""LLM daily-budget guard tests (real Redis logical DB 15, no network LLM calls).

Covers the three guarantees the budget guard makes: the day's spend counter
accumulates, the event path trips ``BudgetExceeded`` once over budget, and chat
(user-facing) is never blocked.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from app.llm.budget import BudgetExceeded, LlmBudgetGuard, spend_key
from app.llm.router import LLMRouter
from tests.test_router import MESSAGES, FakeProvider, _settings

TEST_REDIS_URL = "redis://localhost:6379/15"


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator[Redis]:
    client: Redis = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    await client.flushdb()
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()


def _guard(client: Redis, budget: str) -> LlmBudgetGuard:
    return LlmBudgetGuard(lambda: client, Decimal(budget))


# ===========================================================================
# Counter accumulation
# ===========================================================================


async def test_counter_accumulates(redis_client: Redis) -> None:
    guard = _guard(redis_client, "0.25")
    assert await guard.spent_today() == Decimal("0")
    await guard.record(Decimal("0.10"))
    await guard.record(Decimal("0.05"))
    spent = await guard.spent_today()
    assert abs(spent - Decimal("0.15")) < Decimal("0.0001")


async def test_record_ignores_non_positive(redis_client: Redis) -> None:
    guard = _guard(redis_client, "0.25")
    await guard.record(Decimal("0"))
    await guard.record(Decimal("-1.0"))
    assert await guard.spent_today() == Decimal("0")


async def test_record_sets_expiry(redis_client: Redis) -> None:
    guard = _guard(redis_client, "0.25")
    await guard.record(Decimal("0.01"))
    from datetime import UTC, datetime

    ttl = await redis_client.ttl(spend_key(datetime.now(UTC)))
    assert 0 < ttl <= 60 * 60 * 48


# ===========================================================================
# Over-budget tripping
# ===========================================================================


async def test_raise_if_over_trips_when_over_budget(redis_client: Redis) -> None:
    guard = _guard(redis_client, "0.25")
    await guard.record(Decimal("0.30"))
    assert await guard.is_over_budget() is True
    with pytest.raises(BudgetExceeded):
        await guard.raise_if_over()


async def test_under_budget_does_not_trip(redis_client: Redis) -> None:
    guard = _guard(redis_client, "0.25")
    await guard.record(Decimal("0.10"))
    assert await guard.is_over_budget() is False
    await guard.raise_if_over()  # no raise


async def test_zero_budget_disables_guard(redis_client: Redis) -> None:
    guard = _guard(redis_client, "0")
    await guard.record(Decimal("5.0"))
    assert await guard.is_over_budget() is False
    await guard.raise_if_over()  # no raise


# ===========================================================================
# Router integration: event path trips, chat unaffected, spend recorded
# ===========================================================================


def _router_with_guard(guard: LlmBudgetGuard) -> LLMRouter:
    return LLMRouter(
        settings=_settings(),
        providers={"openai": FakeProvider("openai")},
        budget_guard=guard,
    )


async def test_router_records_spend_on_success(redis_client: Redis) -> None:
    guard = _guard(redis_client, "0.25")
    router = _router_with_guard(guard)
    assert await guard.spent_today() == Decimal("0")

    resp = await router.chat(tier="fast", messages=MESSAGES)
    assert resp.provider == "openai"
    # FakeProvider reports 10 in / 20 out on gpt-4.1-mini -> a real, non-zero cost.
    assert await guard.spent_today() > Decimal("0")


async def test_event_path_trips_but_chat_is_unaffected(redis_client: Redis) -> None:
    """Over budget: the event path (raise_if_over_budget) trips; chat still runs."""
    guard = _guard(redis_client, "0.01")
    await guard.record(Decimal("0.50"))  # push over budget
    router = _router_with_guard(guard)

    # Event-triggered runs consult the guard and pause.
    with pytest.raises(BudgetExceeded):
        await router.raise_if_over_budget()

    # Chat never consults the guard, so a user-facing turn is not blocked.
    resp = await router.chat(tier="fast", messages=MESSAGES)
    assert resp.provider == "openai"


async def test_router_without_guard_is_noop() -> None:
    """A router with no budget guard (unit tests, fake router) never blocks or records."""
    router = LLMRouter(settings=_settings(), providers={"openai": FakeProvider("openai")})
    await router.raise_if_over_budget()  # no raise, no Redis touched
    resp = await router.chat(tier="fast", messages=MESSAGES)
    assert resp.provider == "openai"
