"""LangGraph Postgres checkpointer lifecycle (durable, resumable runs).

Wraps an ``AsyncPostgresSaver`` over a long-lived autocommit connection pool so
runs survive process restarts and multi-turn onboarding resumes by ``thread_id``
(the conversation id). ``init_checkpointer`` is idempotent - safe to call at
startup and lazily on first use - and runs ``setup()`` once to create the
checkpoint tables.
"""

from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_saver: object | None = None
_pool: object | None = None
_lock = asyncio.Lock()


def _psycopg_dsn() -> str:
    """Convert the SQLAlchemy async URL to a plain psycopg DSN."""
    url = get_settings().database_url
    return url.replace("+asyncpg", "").replace("postgresql+psycopg", "postgresql")


async def init_checkpointer() -> object:
    """Return the process-wide checkpointer, initialising it once (idempotent)."""
    global _saver, _pool
    if _saver is not None:
        return _saver
    async with _lock:
        if _saver is not None:
            return _saver
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        pool = AsyncConnectionPool(
            _psycopg_dsn(),
            min_size=1,
            max_size=8,
            open=False,
            kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0},
        )
        await pool.open()
        saver = AsyncPostgresSaver(pool)  # type: ignore[arg-type]
        await saver.setup()
        _pool = pool
        _saver = saver
        logger.info("checkpointer_initialised")
        return _saver


async def close_checkpointer() -> None:
    """Close the checkpointer pool (call on app shutdown)."""
    global _saver, _pool
    if _pool is not None:
        try:
            await _pool.close()  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning("checkpointer_close_failed", error=str(exc))
    _saver = None
    _pool = None
