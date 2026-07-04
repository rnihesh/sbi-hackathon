"""Shared fixtures for the API test suite (chat/customers/nudges/console).

Runs against the real ``sarathi_test`` Postgres database (same convention as
``tests/agents``), truncated before every test. Unlike ``tests/auth`` (which
only needs to override the ``get_db`` FastAPI dependency), the chat/event-trigger
entrypoints (``app.agents.entrypoints.run_chat_turn`` / ``run_event_trigger`` /
``execute_proposal``) call ``app.core.db.get_sessionmaker()`` directly rather
than going through dependency injection - so this conftest also repoints the
process-wide engine/sessionmaker singletons at ``sarathi_test`` for the
duration of each test, restoring them afterwards.

LangGraph's own Postgres checkpointer (``app.agents.checkpointer``) keeps a
separate, direct ``psycopg`` connection pool to whatever database
``DATABASE_URL`` names (the real dev ``sarathi`` db, unless overridden) - its
checkpoint tables are tiny, idempotent, and never asserted on here.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
import pytest
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
from app.core.db import Base, get_db
from app.core.redis import BLOCKING_READ_SOCKET_TIMEOUT_SECONDS
from app.core.security import create_access_token
from app.main import app
from app.models.customer import Customer
from app.models.identity import User

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://sarathi:sarathi@localhost:5432/sarathi_test"
)
TEST_REDIS_URL = "redis://localhost:6379/15"


@pytest_asyncio.fixture(autouse=True)
async def _fresh_checkpointer() -> AsyncIterator[None]:
    """Reset LangGraph's compiled graph + Postgres checkpointer singletons before
    each test.

    Both `app.agents.graph` (`_compiled`) and `app.agents.checkpointer`
    (`_saver`/`_pool`/`_lock`) cache process-wide singletons keyed to whichever
    event loop first initialised them. pytest-asyncio hands each test function
    its own fresh event loop, so anything created by an earlier test breaks the
    next one (a stale `_compiled` graph closes over a now-closed connection pool,
    a stale `_lock` belongs to a dead loop). Resetting per test (and closing the
    checkpointer afterwards) keeps every test's graph+checkpointer bound to its
    own loop.
    """
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
    """Point ``app.core.redis.get_redis()`` at a dedicated, flushed logical DB."""
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
    """Repoint the app-wide engine/sessionmaker singletons at ``sarathi_test``."""
    sm = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    prev_engine, prev_sm = db_module._engine, db_module._sessionmaker
    db_module._engine, db_module._sessionmaker = engine, sm
    try:
        yield
    finally:
        db_module._engine, db_module._sessionmaker = prev_engine, prev_sm


@pytest_asyncio.fixture(autouse=True)
async def _clean_slate(engine: AsyncEngine) -> AsyncIterator[None]:
    """Truncate every domain table before each test (real Postgres, no isolation
    between tests via transactions since app code opens its own sessions)."""
    table_names = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    async with engine.begin() as conn:
        await conn.execute(sa.text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
    yield


@pytest_asyncio.fixture
async def db(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    sm = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    async with sm() as session:
        yield session


@pytest_asyncio.fixture
async def client(engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    sm = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    async def _override_get_db() -> AsyncGenerator[AsyncSession]:
        async with sm() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def make_customer(db: AsyncSession) -> Callable[..., Awaitable[tuple[User, Customer]]]:
    """Factory: create a (User, Customer) pair."""

    async def _make(
        *, email: str | None = None, full_name: str = "Test Customer"
    ) -> tuple[User, Customer]:
        email = email or f"{uuid.uuid4().hex[:10]}@example.com"
        user = User(email=email)
        db.add(user)
        await db.flush()
        customer = Customer(user_id=user.id, full_name=full_name, email=email)
        db.add(customer)
        await db.flush()
        await db.commit()
        return user, customer

    return _make


def auth_cookies(user: User) -> dict[str, str]:
    """Mint a valid access-token cookie dict for ``user`` (no refresh needed in tests)."""
    return {"sarathi_access": create_access_token(str(user.id))}


@pytest.fixture
def staff_email() -> str:
    return "staff@example.com"


@pytest.fixture
def set_staff_emails(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    """Override the staff allowlist for one test, regardless of the real ``.env``."""
    from app.core.config import get_settings

    def _set(value: str) -> None:
        monkeypatch.setattr(get_settings(), "staff_emails", value)

    return _set


@pytest.fixture
def install_fake_router(monkeypatch: pytest.MonkeyPatch) -> Callable[[Any], None]:
    """Swap the LLM router (and embedder) `run_chat_turn`/`run_event_trigger`/
    `execute_proposal` resolve internally for a scripted test double.

    They call `app.agents.entrypoints.get_router()`/`get_embedder()` directly
    (not via FastAPI DI), so the monkeypatch targets those imported names -
    the same `FakeRouter`/`FakeEmbedder` test doubles `tests.agents.conftest`
    already defines for the agent-mesh unit tests.
    """

    def _install(router: Any) -> None:
        import app.agents.entrypoints as entrypoints
        from tests.agents.conftest import FakeEmbedder

        monkeypatch.setattr(entrypoints, "get_router", lambda: router)
        monkeypatch.setattr(entrypoints, "get_embedder", lambda: FakeEmbedder())

    return _install
