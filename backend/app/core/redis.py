"""Async Redis client factory and stream-name constants."""

from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import get_settings

# --- Redis Streams (see docs/architecture.md) ---
TXN_EVENTS = "txn.events"
"""Stream of simulated/real transaction events consumed by the event worker."""

AGENT_ACTIONS = "agent.actions"
"""Stream of agent-emitted actions (proposals, nudges) for live console feeds."""

# Consumer-group names used by workers.
GROUP_ENGAGEMENT = "engagement"
GROUP_CONSOLE = "console"


_client: Redis | None = None


def get_redis() -> Redis:
    """Return the process-wide async Redis client, creating it lazily.

    ``decode_responses=True`` so stream payloads are ``str`` rather than ``bytes``.
    """
    global _client
    if _client is None:
        settings = get_settings()
        _client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            health_check_interval=30,
        )
    return _client


async def close_redis() -> None:
    """Close the Redis client and its connection pool (call on shutdown)."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
