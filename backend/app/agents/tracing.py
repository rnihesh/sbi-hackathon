"""Glass-box run/step tracer.

Writes one ``agent_runs`` row per run and one ``agent_steps`` row per node
transition / LLM call / tool call / guardrail decision. Uses its **own** short
sessions and commits per step, so the trace survives even if the run's main
transaction later rolls back — the trace explorer is a jury feature and must be
trustworthy. Costs/tokens are rolled up onto the run at ``finish``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from time import perf_counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.models.enums import AgentRunStatus, AgentStepKind, AgentTriggerType
from app.models.tracing import AgentRun, AgentStep

logger = get_logger(__name__)


class RunTracer:
    """Accumulates and persists a single agent run's trace."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        agent: str,
        trigger: AgentTriggerType | str,
        customer_id: uuid.UUID | None,
    ) -> None:
        self._sm = sessionmaker
        self._agent = agent
        self._trigger = (
            trigger if isinstance(trigger, AgentTriggerType) else AgentTriggerType(trigger)
        )
        self._customer_id = customer_id
        self._seq = 0
        self._tokens_in = 0
        self._tokens_out = 0
        self._cost = Decimal("0")
        self._started = perf_counter()
        self.run_id: uuid.UUID | None = None

    async def start(self) -> uuid.UUID:
        run = AgentRun(
            agent=self._agent,
            trigger=self._trigger,
            status=AgentRunStatus.RUNNING,
            customer_id=self._customer_id,
        )
        try:
            async with self._sm() as session:
                session.add(run)
                await session.commit()
                self.run_id = run.id
        except Exception as exc:
            logger.warning("trace_run_start_failed", error=str(exc))
            self.run_id = uuid.uuid4()
        return self.run_id

    async def step(
        self,
        *,
        node: str,
        kind: AgentStepKind | str,
        name: str,
        input: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        model: str | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: Decimal = Decimal("0"),
        latency_ms: int | None = None,
    ) -> None:
        self._seq += 1
        self._tokens_in += tokens_in
        self._tokens_out += tokens_out
        self._cost += cost_usd
        step = AgentStep(
            run_id=self.run_id,
            seq=self._seq,
            node=node,
            kind=kind if isinstance(kind, AgentStepKind) else AgentStepKind(kind),
            name=name,
            input=_jsonable(input),
            output=_jsonable(output),
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
        )
        try:
            async with self._sm() as session:
                session.add(step)
                await session.commit()
        except Exception as exc:
            logger.warning("trace_step_failed", node=node, name=name, error=str(exc))

    async def finish(self, status: AgentRunStatus | str = AgentRunStatus.COMPLETED) -> None:
        if self.run_id is None:
            return
        latency_ms = int((perf_counter() - self._started) * 1000)
        status_enum = status if isinstance(status, AgentRunStatus) else AgentRunStatus(status)
        try:
            async with self._sm() as session:
                run = await session.get(AgentRun, self.run_id)
                if run is None:
                    return
                run.status = status_enum
                run.finished_at = _utcnow(session)
                run.tokens_in = self._tokens_in
                run.tokens_out = self._tokens_out
                run.cost_usd = self._cost
                run.latency_ms = latency_ms
                await session.commit()
        except Exception as exc:
            logger.warning("trace_finish_failed", error=str(exc))

    @property
    def totals(self) -> dict[str, Any]:
        return {
            "tokens_in": self._tokens_in,
            "tokens_out": self._tokens_out,
            "cost_usd": str(self._cost),
            "steps": self._seq,
        }


def _utcnow(session: AsyncSession) -> Any:
    from datetime import UTC, datetime

    return datetime.now(UTC)


def _jsonable(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """Best-effort coercion so JSONB insert never fails on odd types."""
    if value is None:
        return None
    import orjson

    try:
        return dict(orjson.loads(orjson.dumps(value, default=str)))
    except Exception:
        return {"_repr": str(value)}
