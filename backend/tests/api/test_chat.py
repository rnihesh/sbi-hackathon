"""Chat API tests: SSE happy path (event sequence + persisted messages) and the
anonymous-vs-authenticated auth boundary.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Message
from tests.agents.conftest import FakeRouter, ScriptedHandler, make_response
from tests.api.conftest import auth_cookies


def _smalltalk_router(reply: str) -> FakeRouter:
    return FakeRouter(
        ScriptedHandler(
            queues={"supervisor:classify": [make_response('{"intent": "smalltalk"}')]},
            default_text=reply,
        )
    )


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
