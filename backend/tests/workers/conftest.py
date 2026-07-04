"""Shared fixtures for the worker test suite (event consumer, prefilter).

Same "real `sarathi_test`, app-wide engine override" convention as
``tests/api/conftest.py`` - duplicated rather than shared via a root conftest to
match this repo's existing per-package-conftest convention (see
``tests/agents/conftest.py`` / ``tests/auth/conftest.py``).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator, AsyncIterator

import pytest_asyncio
import sqlalchemy as sa
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.core.db as db_module
import app.core.redis as redis_module
from app.core.db import Base
from app.core.redis import BLOCKING_READ_SOCKET_TIMEOUT_SECONDS

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://sarathi:sarathi@localhost:5432/sarathi_test"
)
TEST_REDIS_URL = "redis://localhost:6379/15"


@pytest_asyncio.fixture(autouse=True)
async def _fresh_checkpointer() -> AsyncIterator[None]:
    """Reset LangGraph's compiled graph + Postgres checkpointer singletons before
    each test (see the identical fixture in ``tests/api/conftest.py`` for why)."""
    import app.agents.checkpointer as checkpointer_module
    import app.agents.graph as graph_module

    graph_module._compiled = None
    checkpointer_module._saver = None
    checkpointer_module._pool = None
    checkpointer_module._lock = asyncio.Lock()
    yield
    await checkpointer_module.close_checkpointer()


@pytest_asyncio.fixture(autouse=True)
async def _redis_test_db() -> AsyncGenerator[Redis]:
    client: Redis = Redis.from_url(
        TEST_REDIS_URL,
        decode_responses=True,
        socket_timeout=BLOCKING_READ_SOCKET_TIMEOUT_SECONDS,
    )
    await client.flushdb()
    previous = redis_module._client
    redis_module._client = client
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()
        redis_module._client = previous


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    import app.models  # noqa: F401 - register all tables on Base.metadata

    eng = create_async_engine(TEST_DB_URL, echo=False, pool_pre_ping=True)
    async with eng.begin() as conn:
        await conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _app_db_override(engine: AsyncEngine) -> AsyncIterator[None]:
    sm = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    prev_engine, prev_sm = db_module._engine, db_module._sessionmaker
    db_module._engine, db_module._sessionmaker = engine, sm
    try:
        yield
    finally:
        db_module._engine, db_module._sessionmaker = prev_engine, prev_sm


@pytest_asyncio.fixture(autouse=True)
async def _clean_slate(engine: AsyncEngine) -> AsyncIterator[None]:
    table_names = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    async with engine.begin() as conn:
        await conn.execute(sa.text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
    yield


@pytest_asyncio.fixture
async def db(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    sm = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    async with sm() as session:
        yield session
