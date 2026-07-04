"""Test harness for the agent mesh: real test DB + fake router/embedder.

Uses a real Postgres test database (``sarathi_test``, pgvector enabled) so vector
recall, the audit hash-chain, and tracing exercise real SQL. LLM traffic is
served by a deterministic :class:`FakeRouter` (scripted tool calls + text); no
network. Every runtime path stays real — only the model is faked.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.llm.base import ChatMessage, LLMResponse, ToolCall, ToolSpec

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://sarathi:sarathi@localhost:5432/sarathi_test",
)


# ---------------------------------------------------------------------------
# Fake LLM router (scripted, deterministic)
# ---------------------------------------------------------------------------

Handler = Callable[..., LLMResponse]


def make_response(
    text: str = "",
    tool_calls: list[ToolCall] | None = None,
    *,
    model: str = "fake-smart",
    tokens_in: int = 12,
    tokens_out: int = 8,
) -> LLMResponse:
    return LLMResponse(
        text=text,
        tool_calls=tool_calls or [],
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        model=model,
        provider="fake",
        cost_usd=Decimal("0.0001"),
    )


@dataclass
class FakeRouter:
    """Scriptable router double implementing the router's ``chat`` surface."""

    handler: Handler
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def chat(
        self,
        *,
        tier: str = "smart",
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        json_mode: bool = False,
        purpose: str | None = None,
    ) -> LLMResponse:
        self.calls.append(
            {
                "purpose": purpose,
                "tier": tier,
                "json_mode": json_mode,
                "messages": len(messages),
                "tools": [t.name for t in (tools or [])],
                "system": system,
            }
        )
        return self.handler(
            purpose=purpose, messages=messages, tools=tools, json_mode=json_mode, system=system
        )


class ScriptedHandler:
    """A handler that returns queued responses per purpose-prefix, else a default."""

    def __init__(
        self,
        *,
        default_text: str = "Here is a helpful, compliant answer.",
        queues: dict[str, list[LLMResponse]] | None = None,
    ) -> None:
        self._queues = {k: list(v) for k, v in (queues or {}).items()}
        self._default = default_text

    def __call__(self, *, purpose: str | None, **_: Any) -> LLMResponse:
        purpose = purpose or ""
        for prefix, queue in self._queues.items():
            if purpose.startswith(prefix) and queue:
                return queue.pop(0)
        return make_response(self._default)


# ---------------------------------------------------------------------------
# Fake embedder (deterministic 1536-d vectors)
# ---------------------------------------------------------------------------

_DIM = 1536
_AXES = {"alpha": 0, "beta": 1, "gamma": 2, "delta": 3, "salary": 4, "loan": 5}


def _unit_vector(text: str) -> list[float]:
    """Deterministic vector: axis chosen by the first known keyword present."""
    vec = [0.0] * _DIM
    lowered = text.lower()
    axis = next((i for kw, i in _AXES.items() if kw in lowered), None)
    if axis is None:
        # Stable hashed fallback so unrelated text still embeds deterministically.
        axis = (sum(ord(c) for c in lowered) % (_DIM - 16)) + 8
    vec[axis] = 1.0
    return vec


@dataclass
class FakeEmbedder:
    """Deterministic embedder; ``available`` is always True."""

    vector_fn: Callable[[str], list[float]] = _unit_vector

    def available(self) -> bool:
        return True

    async def embed(self, text: str) -> list[float]:
        return self.vector_fn(text)

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.vector_fn(t) for t in texts]


# ---------------------------------------------------------------------------
# Database fixtures (real sarathi_test)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[Any]:
    import app.models  # noqa: F401 - register all tables on Base.metadata
    from app.core.db import Base

    eng = create_async_engine(TEST_DB_URL, echo=False, pool_pre_ping=True)
    async with eng.begin() as conn:
        await conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def sessionmaker_test(engine: Any) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@pytest_asyncio.fixture
async def db(
    engine: Any, sessionmaker_test: async_sessionmaker[AsyncSession]
) -> AsyncIterator[AsyncSession]:
    import app.models  # noqa: F401
    from app.core.db import Base

    # Clean slate per test.
    table_names = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    async with engine.begin() as conn:
        await conn.execute(sa.text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))

    async with sessionmaker_test() as session:
        yield session


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest_asyncio.fixture
async def make_ctx(
    db: AsyncSession,
    sessionmaker_test: async_sessionmaker[AsyncSession],
    fake_embedder: FakeEmbedder,
) -> Callable[..., Any]:
    """Return an async builder for a per-run AgentContext wired to the test DB."""
    from app.agents.context import AgentContext
    from app.agents.guardrails import PIIRedactor
    from app.agents.tracing import RunTracer

    async def _build(
        router: Any,
        *,
        customer_id: Any = None,
        emitter: Any = None,
        conversation_id: str = "conv-test",
    ) -> AgentContext:
        tracer = RunTracer(
            sessionmaker_test, agent="supervisor", trigger="chat", customer_id=customer_id
        )
        await tracer.start()
        ctx = AgentContext(
            session=db,
            sessionmaker=sessionmaker_test,
            router=router,
            embedder=fake_embedder,
            tracer=tracer,
            emitter=emitter,
            customer_id=customer_id,
            conversation_id=conversation_id,
        )
        ctx.redaction = PIIRedactor().redact("")
        return ctx

    return _build
