"""Shared fixtures for the auth test suite.

Runs against the real, native Postgres configured via app settings, wrapped in a
per-test connection + outer transaction (with nested savepoints so the app's own
``session.commit()`` calls never escape it) that is always rolled back — nothing here
ever persists to the shared dev database. Redis uses a dedicated logical DB (index 15)
that is flushed before and after every test.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.core.redis as redis_module
from app.core.config import get_settings
from app.core.db import get_db
from app.main import app

TEST_REDIS_URL = "redis://localhost:6379/15"


@pytest.fixture(autouse=True)
async def _redis_test_db() -> AsyncGenerator[Redis]:
    """Point ``app.core.redis.get_redis()`` at a dedicated, flushed logical DB."""
    client: Redis = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    await client.flushdb()
    previous = redis_module._client
    redis_module._client = client
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()
        redis_module._client = previous


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession]:
    """A session bound to one connection + outer transaction, rolled back after the test.

    Deliberately uses its own engine (rather than ``app.core.db.get_engine()``'s
    process-wide singleton) created and disposed within this fixture's own event loop:
    pytest-asyncio gives each test function a fresh loop, and asyncpg connections
    created under a prior loop break when reused under a new one.
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            session_factory = async_sessionmaker(
                bind=conn,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            async with session_factory() as session:
                yield session
            await trans.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[httpx.AsyncClient]:
    """An httpx client driving the real FastAPI app in-process.

    ``get_db`` is overridden to hand out the test's own transactional session so
    everything a request does is visible to (and rolled back with) ``db_session``.
    """

    async def _override_get_db() -> AsyncGenerator[AsyncSession]:
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_db] = _override_get_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)
