"""Per-run agent context: dependencies + streaming, passed via graph config.

``AgentContext`` bundles everything a node/tool needs but that must NOT be
checkpointed (DB session, router, tracer, redaction map, event emitter). It is
handed to nodes through ``config["configurable"]["ctx"]`` - LangGraph checkpoints
state channels, never the config, so this stays out of the persisted snapshot.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.guardrails import AuditTrail, PIIRedactor, PolicyEngine, RedactionResult
from app.agents.tracing import RunTracer
from app.core.logging import get_logger
from app.llm.embeddings import Embedder
from app.llm.router import LLMRouter

logger = get_logger(__name__)

_DONE = object()  # queue sentinel


class EventEmitter:
    """Async fan-out of streamed run events to a single consumer (the SSE loop)."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Any] = asyncio.Queue()

    async def emit(self, event: dict[str, Any]) -> None:
        await self._queue.put(event)

    async def close(self) -> None:
        await self._queue.put(_DONE)

    async def stream(self) -> Any:
        """Yield events until ``close`` is called."""
        while True:
            item = await self._queue.get()
            if item is _DONE:
                return
            yield item


@dataclass(slots=True)
class AgentContext:
    """Everything a run needs that is not part of serialisable state."""

    session: AsyncSession
    sessionmaker: async_sessionmaker[AsyncSession]
    router: LLMRouter
    embedder: Embedder
    tracer: RunTracer
    redactor: PIIRedactor = field(default_factory=PIIRedactor)
    policy: PolicyEngine = field(default_factory=PolicyEngine)
    audit: AuditTrail = field(default_factory=AuditTrail)
    emitter: EventEmitter | None = None
    redaction: RedactionResult | None = None
    customer_id: uuid.UUID | None = None
    conversation_id: str | None = None

    async def emit(self, event: dict[str, Any]) -> None:
        if self.emitter is not None:
            await self.emitter.emit(event)

    def restore_args(self, args: dict[str, Any]) -> dict[str, Any]:
        """Restore redacted placeholders in tool args to real PII values."""
        if self.redaction is None:
            return args
        return self.redaction.restore_args(args)

    async def audit_record(
        self,
        actor: str,
        action: str,
        entity: str,
        entity_id: str | None,
        payload: dict[str, Any],
    ) -> None:
        """Append a hash-chained audit row in its own committed transaction."""
        try:
            async with self.sessionmaker() as session:
                await self.audit.record(session, actor, action, entity, entity_id, payload)
                await session.commit()
        except Exception as exc:
            logger.warning("audit_record_failed", action=action, error=str(exc))
