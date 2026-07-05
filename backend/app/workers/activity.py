"""Console live-feed publisher.

Wires agent output onto the ``agent.actions`` Redis Stream that
``GET /console/feed`` tails, **without** touching `app.agents` internals: both the
chat SSE path (`app.api.v1.chat`) and the event-consumer path
(`app.workers.event_consumer`) already receive everything they need - the run's
summary/id and the `proposals` / `life_events` / `nudges` lists the agent mesh
recorded on its state - from the public `run_chat_turn` / `run_event_trigger`
entrypoints. This module just shapes that into the envelope the console feed reads.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import orjson
from redis.asyncio import Redis

from app.core.logging import get_logger
from app.core.redis import AGENT_ACTIONS

logger = get_logger(__name__)

ActivityType = Literal["agent_run", "proposal", "life_event", "nudge", "handoff"]


async def publish_activity(
    redis: Redis,
    *,
    type: ActivityType,
    customer_id: str | uuid.UUID | None,
    summary: str,
    ref_id: str | uuid.UUID | None = None,
) -> None:
    """Best-effort ``XADD`` of one console-feed envelope. Never raises."""
    envelope: dict[str, Any] = {
        "type": type,
        "ts": datetime.now(UTC).isoformat(),
        "customer_id": str(customer_id) if customer_id else None,
        "summary": summary,
        "ref_id": str(ref_id) if ref_id else None,
    }
    try:
        await redis.xadd(AGENT_ACTIONS, {"data": orjson.dumps(envelope).decode()})
    except Exception as exc:
        logger.warning("activity_publish_failed", type=type, error=str(exc))


async def publish_handoff(
    redis: Redis,
    *,
    customer_id: str | uuid.UUID | None,
    handoff: dict[str, Any],
) -> None:
    """Publish one ``handoff`` console-feed envelope. Never raises.

    Shared by :func:`publish_run_result` (authenticated turns) and the chat
    entrypoint's anonymous-prospect path, so a prospect asking for a human still
    reaches the queue's live feed even though anonymous turns otherwise stay off it."""
    urgency = handoff.get("urgency", "normal")
    reason = str(handoff.get("reason", "")).strip()
    summary = f"Human handoff requested ({urgency})"
    if reason:
        summary = f"{summary}: {reason}"
    await publish_activity(
        redis,
        type="handoff",
        customer_id=customer_id,
        summary=summary[:200],
        ref_id=handoff.get("id"),
    )


async def publish_run_result(
    redis: Redis,
    *,
    customer_id: str | uuid.UUID | None,
    run_id: str,
    run_summary: str,
    proposals: list[str],
    life_events: list[dict[str, Any]],
    nudges: list[str],
    handoffs: list[dict[str, Any]] | None = None,
) -> None:
    """Publish one ``agent_run`` envelope, plus one per proposal/life-event/nudge/
    handoff the run created - shared by the chat and event-trigger paths so both
    surface identical console-feed shapes for the same underlying agent output."""
    await publish_activity(
        redis, type="agent_run", customer_id=customer_id, summary=run_summary, ref_id=run_id
    )
    for proposal_id in proposals:
        await publish_activity(
            redis,
            type="proposal",
            customer_id=customer_id,
            summary="Proposal created, pending approval",
            ref_id=proposal_id,
        )
    for life_event in life_events:
        await publish_activity(
            redis,
            type="life_event",
            customer_id=customer_id,
            summary=f"Life event detected: {life_event.get('type', 'unknown')}",
            ref_id=life_event.get("id"),
        )
    for nudge_id in nudges:
        await publish_activity(
            redis, type="nudge", customer_id=customer_id, summary="Nudge sent", ref_id=nudge_id
        )
    for handoff in handoffs or []:
        await publish_handoff(redis, customer_id=customer_id, handoff=handoff)
