"""Chat API tests: SSE happy path (event sequence + persisted messages) and the
anonymous-vs-authenticated auth boundary.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.agents.entrypoints as entrypoints
from app.llm.base import LLMResponse
from app.llm.budget import BudgetExceeded
from app.models.conversation import Conversation, Message
from app.models.enums import MemoryKind
from app.models.memory import AgentMemory
from tests.agents.conftest import FakeRouter, ScriptedHandler, make_response
from tests.api.conftest import auth_cookies


def _smalltalk_router(reply: str) -> FakeRouter:
    return FakeRouter(
        ScriptedHandler(
            queues={"supervisor:classify": [make_response('{"intent": "smalltalk"}')]},
            default_text=reply,
        )
    )


def _title_router(*, reply: str, titles: list[str], turns: int = 1) -> FakeRouter:
    """Router that scripts ``turns`` smalltalk classifications plus a queue of
    ``chat:title`` responses (each a raw ``{"title": ...}`` JSON string)."""
    return FakeRouter(
        ScriptedHandler(
            queues={
                "supervisor:classify": [
                    make_response('{"intent": "smalltalk"}') for _ in range(turns)
                ],
                "chat:title": [make_response(t) for t in titles],
            },
            default_text=reply,
        )
    )


class _RaiseOnTitle:
    """Handler that raises for the title call and behaves normally otherwise -
    exercises the swallow-and-log path of ``_maybe_generate_title``."""

    def __init__(self, reply: str) -> None:
        self._inner = ScriptedHandler(
            queues={"supervisor:classify": [make_response('{"intent": "smalltalk"}')]},
            default_text=reply,
        )

    def __call__(self, *, purpose: str | None = None, **kwargs: Any) -> LLMResponse:
        if purpose == "chat:title":
            raise RuntimeError("title provider exploded")
        return self._inner(purpose=purpose, **kwargs)


async def _drain_titles() -> None:
    """Await any in-flight fire-and-forget title tasks (test determinism)."""
    pending = [t for t in list(entrypoints._title_tasks) if not t.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def _send(
    client: httpx.AsyncClient, conv_id: str, text: str, user: Any
) -> httpx.Response:
    resp = await client.post(
        f"/api/v1/chat/sessions/{conv_id}/messages",
        json={"text": text},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 200
    return resp


async def _create_session(client: httpx.AsyncClient, user: Any) -> str:
    resp = await client.post("/api/v1/chat/sessions", json={}, cookies=auth_cookies(user))
    assert resp.status_code == 200
    return str(resp.json()["conversation_id"])


def _parse_sse(body: str) -> list[dict[str, Any]]:
    """Parse a raw `text/event-stream` body into ``[{"event": ..., "data": ...}]``."""
    events: list[dict[str, Any]] = []
    for block in body.split("\r\n\r\n"):
        block = block.strip("\r\n")
        if not block:
            continue
        event_type = "message"
        data_lines: list[str] = []
        for line in block.split("\r\n"):
            if line.startswith("event:"):
                event_type = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
            elif line.startswith(":"):
                continue  # ping/comment
        if data_lines:
            events.append({"event": event_type, "data": "\n".join(data_lines)})
    return events


async def test_chat_sse_happy_path_persists_messages(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    install_fake_router: Callable[[Any], None],
) -> None:
    user, customer = await make_customer()
    install_fake_router(_smalltalk_router("Hello! I'm Sarathi, your banking assistant."))

    create_resp = await client.post(
        "/api/v1/chat/sessions", json={}, cookies=auth_cookies(user)
    )
    assert create_resp.status_code == 200
    conversation_id = create_resp.json()["conversation_id"]

    resp = await client.post(
        f"/api/v1/chat/sessions/{conversation_id}/messages",
        json={"text": "hi who are you"},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(resp.text)
    event_types = [e["event"] for e in events]
    assert "run_started" in event_types
    assert "agent" in event_types
    assert "token" in event_types
    assert event_types[-1] == "done"

    result = await db.execute(select(Message))
    messages = result.scalars().all()
    roles = sorted(m.role.value for m in messages)
    assert roles == ["assistant", "user"]

    session_resp = await client.get(
        f"/api/v1/chat/sessions/{conversation_id}", cookies=auth_cookies(user)
    )
    assert session_resp.status_code == 200
    body = session_resp.json()
    assert body["customer_id"] == str(customer.id)
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]


async def test_anon_chat_is_allowed_without_auth(
    client: httpx.AsyncClient, install_fake_router: Callable[[Any], None]
) -> None:
    install_fake_router(_smalltalk_router("Hi there, welcome to Sarathi."))

    create_resp = await client.post("/api/v1/chat/sessions", json={})
    assert create_resp.status_code == 200
    conversation_id = create_resp.json()["conversation_id"]

    resp = await client.post(
        f"/api/v1/chat/sessions/{conversation_id}/messages", json={"text": "hello"}
    )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert events[-1]["event"] == "done"


async def test_cannot_read_another_customers_conversation(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    install_fake_router: Callable[[Any], None],
) -> None:
    owner, _owner_customer = await make_customer(email="owner@example.com")
    other, _other_customer = await make_customer(email="other@example.com")
    install_fake_router(_smalltalk_router("Hi!"))

    create_resp = await client.post(
        "/api/v1/chat/sessions", json={}, cookies=auth_cookies(owner)
    )
    conversation_id = create_resp.json()["conversation_id"]
    await client.post(
        f"/api/v1/chat/sessions/{conversation_id}/messages",
        json={"text": "hi"},
        cookies=auth_cookies(owner),
    )

    resp = await client.get(
        f"/api/v1/chat/sessions/{conversation_id}", cookies=auth_cookies(other)
    )
    assert resp.status_code == 403


async def test_me_endpoints_require_auth(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/me")
    assert resp.status_code == 401
    resp2 = await client.get("/api/v1/me/dashboard")
    assert resp2.status_code == 401
    resp3 = await client.get("/api/v1/me/nudges")
    assert resp3.status_code == 401


# ---------------------------------------------------------------------------
# LLM conversation titles (fire-and-forget)
# ---------------------------------------------------------------------------


async def test_first_turn_generates_and_persists_llm_title(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    install_fake_router: Callable[[Any], None],
) -> None:
    user, _customer = await make_customer()
    install_fake_router(
        _title_router(
            reply="Sure, happy to help.",
            titles=['{"title": "Opening A Savings Account"}'],
        )
    )

    conv_id = await _create_session(client, user)
    await _send(client, conv_id, "how do I open a savings account", user)
    await _drain_titles()

    conv = await db.get(Conversation, uuid.UUID(conv_id))
    assert conv is not None
    assert conv.title == "Opening A Savings Account"


async def test_title_generation_failure_leaves_title_null(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    install_fake_router: Callable[[Any], None],
) -> None:
    user, _customer = await make_customer()
    install_fake_router(FakeRouter(_RaiseOnTitle("Sure, happy to help.")))

    conv_id = await _create_session(client, user)
    await _send(client, conv_id, "hello there", user)
    await _drain_titles()  # the swallowed error must not surface here

    conv = await db.get(Conversation, uuid.UUID(conv_id))
    assert conv is not None
    assert conv.title is None


async def test_second_turn_does_not_regenerate_title(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    install_fake_router: Callable[[Any], None],
) -> None:
    user, _customer = await make_customer()
    router = _title_router(
        reply="Sure, happy to help.",
        titles=['{"title": "First Title Here"}', '{"title": "Second Title Wrong"}'],
        turns=2,
    )
    install_fake_router(router)

    conv_id = await _create_session(client, user)
    await _send(client, conv_id, "first question", user)
    await _drain_titles()
    await _send(client, conv_id, "second question", user)
    await _drain_titles()

    conv = await db.get(Conversation, uuid.UUID(conv_id))
    assert conv is not None
    assert conv.title == "First Title Here"  # unchanged - dedup on title IS NULL
    # The title LLM was invoked exactly once across both turns.
    assert sum(1 for c in router.calls if c["purpose"] == "chat:title") == 1


# ---------------------------------------------------------------------------
# Durable-fact extraction (fire-and-forget)
# ---------------------------------------------------------------------------


class _OverBudgetRouter(FakeRouter):
    """FakeRouter whose budget guard trips - chat is untouched, extraction skips."""

    async def raise_if_over_budget(self) -> None:
        raise BudgetExceeded("daily LLM budget reached")


def _facts_router(*, reply: str, facts_json: str, turns: int = 1) -> FakeRouter:
    """Router scripting ``turns`` smalltalk classifications, one title, and a queue
    of ``memory:facts`` extraction responses (raw ``{"facts": [...]}`` JSON)."""
    return FakeRouter(
        ScriptedHandler(
            queues={
                "supervisor:classify": [
                    make_response('{"intent": "smalltalk"}') for _ in range(turns)
                ],
                "chat:title": [make_response('{"title": "A Thread"}') for _ in range(turns)],
                "memory:facts": [make_response(facts_json) for _ in range(turns)],
            },
            default_text=reply,
        )
    )


async def _drain_facts() -> None:
    """Await any in-flight fire-and-forget fact-extraction tasks (test determinism)."""
    pending = [t for t in list(entrypoints._fact_tasks) if not t.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def _fact_count(router: FakeRouter) -> int:
    return sum(1 for c in router.calls if (c["purpose"] or "").startswith("memory:facts"))


async def _stored_facts(db: AsyncSession, customer_id: Any) -> list[AgentMemory]:
    rows = await db.scalars(
        select(AgentMemory).where(
            AgentMemory.customer_id == customer_id,
            AgentMemory.kind.in_([MemoryKind.FACT, MemoryKind.PREFERENCE]),
        )
    )
    return list(rows.all())


async def test_first_turn_extracts_and_stores_durable_facts(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    install_fake_router: Callable[[Any], None],
) -> None:
    user, customer = await make_customer()
    install_fake_router(
        _facts_router(
            reply="Noted, thanks for sharing.",
            facts_json=(
                '{"facts": ['
                '{"fact": "has two kids", "kind": "fact"}, '
                '{"fact": "is risk-averse", "kind": "preference"}]}'
            ),
        )
    )

    conv_id = await _create_session(client, user)
    await _send(client, conv_id, "I have two kids and I hate risk", user)
    await _drain_facts()

    rows = await _stored_facts(db, customer.id)
    texts = {r.text for r in rows}
    kinds = {r.kind for r in rows}
    assert "has two kids" in texts
    assert "is risk-averse" in texts
    assert MemoryKind.FACT in kinds
    assert MemoryKind.PREFERENCE in kinds


async def test_fact_extraction_frequency_capped_within_five_turns(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    install_fake_router: Callable[[Any], None],
) -> None:
    user, _customer = await make_customer()
    router = _facts_router(
        reply="ok",
        facts_json='{"facts": [{"fact": "works at Infosys", "kind": "fact"}]}',
        turns=2,
    )
    install_fake_router(router)

    conv_id = await _create_session(client, user)
    await _send(client, conv_id, "turn one", user)
    await _drain_facts()
    await _send(client, conv_id, "turn two", user)
    await _drain_facts()

    # Cap: at most one extraction call per conversation per 5 turns (turn 1 only).
    assert _fact_count(router) == 1


async def test_fact_extraction_skipped_when_over_budget(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    install_fake_router: Callable[[Any], None],
) -> None:
    user, customer = await make_customer()
    handler = ScriptedHandler(
        queues={
            "supervisor:classify": [make_response('{"intent": "smalltalk"}')],
            "chat:title": [make_response('{"title": "A Thread"}')],
        },
        default_text="ok",
    )
    router = _OverBudgetRouter(handler)
    install_fake_router(router)

    conv_id = await _create_session(client, user)
    await _send(client, conv_id, "I have two kids", user)
    await _drain_facts()  # extraction is a luxury: budget guard trips, it skips

    assert _fact_count(router) == 0
    assert await _stored_facts(db, customer.id) == []


# ---------------------------------------------------------------------------
# Session list: preview + title
# ---------------------------------------------------------------------------


async def test_session_list_includes_preview_and_title(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    install_fake_router: Callable[[Any], None],
) -> None:
    user, _customer = await make_customer()
    install_fake_router(
        _title_router(reply="Here is your balance.", titles=['{"title": "Checking My Balance"}'])
    )

    conv_id = await _create_session(client, user)
    await _send(client, conv_id, "what is my balance", user)
    await _drain_titles()

    resp = await client.get("/api/v1/chat/sessions", cookies=auth_cookies(user))
    assert resp.status_code == 200
    sessions = resp.json()["sessions"]
    assert len(sessions) == 1
    session = sessions[0]
    assert session["conversation_id"] == conv_id
    assert session["title"] == "Checking My Balance"
    assert session["preview"] == "Here is your balance."  # last message content
    assert session["message_count"] == 2


# ---------------------------------------------------------------------------
# Rename
# ---------------------------------------------------------------------------


async def test_rename_conversation(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    install_fake_router: Callable[[Any], None],
) -> None:
    user, _customer = await make_customer()
    install_fake_router(_smalltalk_router("Hi!"))
    conv_id = await _create_session(client, user)
    await _send(client, conv_id, "hi", user)

    resp = await client.patch(
        f"/api/v1/chat/sessions/{conv_id}",
        json={"title": "  My Renamed Thread  "},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "My Renamed Thread"  # stripped

    conv = await db.get(Conversation, uuid.UUID(conv_id))
    assert conv is not None and conv.title == "My Renamed Thread"

    listing = await client.get("/api/v1/chat/sessions", cookies=auth_cookies(user))
    assert listing.json()["sessions"][0]["title"] == "My Renamed Thread"


async def test_rename_validation_rejects_blank_and_overlong(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    install_fake_router: Callable[[Any], None],
) -> None:
    user, _customer = await make_customer()
    install_fake_router(_smalltalk_router("Hi!"))
    conv_id = await _create_session(client, user)
    await _send(client, conv_id, "hi", user)

    for bad in ("", "   ", "x" * 101):
        resp = await client.patch(
            f"/api/v1/chat/sessions/{conv_id}",
            json={"title": bad},
            cookies=auth_cookies(user),
        )
        assert resp.status_code == 422


async def test_rename_missing_conversation_404(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
) -> None:
    user, _customer = await make_customer()
    resp = await client.patch(
        f"/api/v1/chat/sessions/{uuid.uuid4()}",
        json={"title": "Whatever"},
        cookies=auth_cookies(user),
    )
    assert resp.status_code == 404


async def test_rename_forbidden_cross_tenant(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    install_fake_router: Callable[[Any], None],
) -> None:
    owner, _oc = await make_customer(email="owner@example.com")
    other, _otc = await make_customer(email="other@example.com")
    install_fake_router(_smalltalk_router("Hi!"))
    conv_id = await _create_session(client, owner)
    await _send(client, conv_id, "hi", owner)

    resp = await client.patch(
        f"/api/v1/chat/sessions/{conv_id}",
        json={"title": "Hijacked"},
        cookies=auth_cookies(other),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


async def test_delete_conversation_cascades_messages(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    install_fake_router: Callable[[Any], None],
) -> None:
    user, _customer = await make_customer()
    install_fake_router(_smalltalk_router("Hi!"))
    conv_id = await _create_session(client, user)
    await _send(client, conv_id, "hi", user)

    resp = await client.delete(
        f"/api/v1/chat/sessions/{conv_id}", cookies=auth_cookies(user)
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"

    # Conversation and its messages are gone.
    gone = await client.get(f"/api/v1/chat/sessions/{conv_id}", cookies=auth_cookies(user))
    assert gone.status_code == 404
    remaining = (await db.execute(select(Message))).scalars().all()
    assert remaining == []
    listing = await client.get("/api/v1/chat/sessions", cookies=auth_cookies(user))
    assert listing.json()["sessions"] == []


async def test_delete_missing_conversation_404(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
) -> None:
    user, _customer = await make_customer()
    resp = await client.delete(
        f"/api/v1/chat/sessions/{uuid.uuid4()}", cookies=auth_cookies(user)
    )
    assert resp.status_code == 404


async def test_delete_forbidden_cross_tenant(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    install_fake_router: Callable[[Any], None],
) -> None:
    owner, _oc = await make_customer(email="owner@example.com")
    other, _otc = await make_customer(email="other@example.com")
    install_fake_router(_smalltalk_router("Hi!"))
    conv_id = await _create_session(client, owner)
    await _send(client, conv_id, "hi", owner)

    resp = await client.delete(
        f"/api/v1/chat/sessions/{conv_id}", cookies=auth_cookies(other)
    )
    assert resp.status_code == 403


async def test_get_missing_conversation_returns_404(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
) -> None:
    user, _customer = await make_customer()
    resp = await client.get(
        f"/api/v1/chat/sessions/{uuid.uuid4()}", cookies=auth_cookies(user)
    )
    assert resp.status_code == 404
