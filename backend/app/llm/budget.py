"""Daily LLM spend guard backed by a cheap per-day Redis counter.

Every successful router call increments a ``llm:spend:{YYYY-MM-DD}`` (UTC) counter
by its USD cost (``INCRBYFLOAT``, expiring a couple of days out so the keyspace
stays tiny). The event pipeline consults the counter *before* spending on an
automated agent run and pauses (raises :class:`BudgetExceeded`) once the day's
spend crosses ``llm_daily_budget_usd``. User-facing chat never consults the guard,
so it is never blocked - only the unattended event path throttles itself.

The guard is deliberately best-effort: a Redis hiccup while *recording* never
breaks an LLM call, and enforcement fails open (a read error means "not over
budget") so a transient Redis blip can never wedge the whole event pipeline.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.llm.base import LLMError

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(__name__)

_KEY_PREFIX = "llm:spend"
_KEY_TTL_SECONDS = 60 * 60 * 48
"""Two days: long enough that the current UTC day's key never expires under it,
short enough that yesterday's counter self-evicts."""


class BudgetExceeded(LLMError):  # noqa: N818 - name mandated by the router API contract
    """Raised when the day's LLM spend has crossed the configured budget.

    A subclass of :class:`LLMError` so any caller already handling router errors
    treats it as one, while the event path can catch it specifically to pause
    (rather than dead-letter) an automated run.
    """


def spend_key(now: datetime) -> str:
    """Redis key for ``now``'s UTC day spend counter."""
    return f"{_KEY_PREFIX}:{now.astimezone(UTC).date().isoformat()}"


class LlmBudgetGuard:
    """Records and checks the current UTC day's LLM spend against a ceiling."""

    def __init__(
        self,
        redis_factory: Callable[[], Redis],
        budget_usd: Decimal,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._redis_factory = redis_factory
        self._budget = budget_usd
        self._clock = clock

    @property
    def budget_usd(self) -> Decimal:
        return self._budget

    async def record(self, cost_usd: Decimal) -> None:
        """Add ``cost_usd`` to today's counter (best-effort; never raises)."""
        if cost_usd <= 0:
            return
        key = spend_key(self._clock())
        try:
            redis = self._redis_factory()
            await redis.incrbyfloat(key, float(cost_usd))
            await redis.expire(key, _KEY_TTL_SECONDS)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("llm_budget_record_failed", error=str(exc))

    async def spent_today(self) -> Decimal:
        """Today's accumulated spend (``Decimal('0')`` on any read failure)."""
        key = spend_key(self._clock())
        try:
            raw = await self._redis_factory().get(key)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("llm_budget_read_failed", error=str(exc))
            return Decimal("0")
        if raw is None:
            return Decimal("0")
        try:
            return Decimal(str(raw))
        except Exception:  # pragma: no cover - malformed counter
            return Decimal("0")

    async def is_over_budget(self) -> bool:
        """Whether today's spend has reached/exceeded the budget."""
        if self._budget <= 0:
            return False  # a zero/negative budget disables the guard entirely
        return await self.spent_today() >= self._budget

    async def raise_if_over(self) -> None:
        """Raise :class:`BudgetExceeded` when today's spend is over budget."""
        if await self.is_over_budget():
            spent = await self.spent_today()
            raise BudgetExceeded(
                f"daily LLM budget of ${self._budget} reached "
                f"(spent ${spent} today); pausing event-triggered runs"
            )
