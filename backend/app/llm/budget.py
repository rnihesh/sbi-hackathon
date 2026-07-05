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

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.llm.base import LLMError

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(__name__)

SPEND_KEY_PREFIX = "llm:spend"
"""Prefix of the per-UTC-day spend counter keys (``llm:spend:{YYYY-MM-DD}``).
Public so the demo-reset op can flush stale counters after truncating the ledger."""

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
    return f"{SPEND_KEY_PREFIX}:{now.astimezone(UTC).date().isoformat()}"


class LlmBudgetGuard:
    """Records and checks the current UTC day's LLM spend against a ceiling."""

    def __init__(
        self,
        redis_factory: Callable[[], Redis],
        budget_usd: Decimal,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        budget_resolver: Callable[[], Awaitable[Decimal]] | None = None,
    ) -> None:
        self._redis_factory = redis_factory
        self._budget = budget_usd
        self._clock = clock
        # Optional async resolver for the *effective* budget (a runtime override
        # read from Redis, falling back to the static ceiling). Injected by the
        # router's composition root; absent in unit tests, which then use the
        # static ``budget_usd`` and never touch runtime settings.
        self._budget_resolver = budget_resolver

    @property
    def budget_usd(self) -> Decimal:
        """The static (configured) ceiling. Live checks use :meth:`effective_budget`."""
        return self._budget

    async def effective_budget(self) -> Decimal:
        """Resolve the budget to enforce: the runtime override if a resolver is
        wired and succeeds, otherwise the static ceiling (fail-safe)."""
        if self._budget_resolver is not None:
            try:
                return await self._budget_resolver()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("llm_budget_resolver_failed", error=str(exc))
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
        """Whether today's spend has reached/exceeded the effective budget."""
        budget = await self.effective_budget()
        if budget <= 0:
            return False  # a zero/negative budget disables the guard entirely
        return await self.spent_today() >= budget

    async def raise_if_over(self) -> None:
        """Raise :class:`BudgetExceeded` when today's spend is over the effective budget."""
        budget = await self.effective_budget()
        if budget <= 0:
            return
        spent = await self.spent_today()
        if spent >= budget:
            raise BudgetExceeded(
                f"daily LLM budget of ${budget} reached "
                f"(spent ${spent} today); pausing event-triggered runs"
            )
