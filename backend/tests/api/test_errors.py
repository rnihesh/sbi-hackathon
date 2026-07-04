"""Structured error envelope + request-id propagation + body-size cap tests.

Covers the four error classes routed through :mod:`app.core.errors`
(HTTPException 404, validation 422, unhandled 500, oversized 413), that every one
carries the ``{error: {code, message, request_id}, detail}`` shape with the
back-compat ``detail`` alias, and that an inbound ``X-Request-ID`` is echoed in
both the body and the response header.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import get_settings
from app.core.errors import ERROR_RING_KEY
from app.core.redis import get_redis

pytestmark = pytest.mark.anyio


async def test_http_exception_uses_envelope_and_propagates_request_id(
    client: httpx.AsyncClient,
) -> None:
    request_id = "fixed-req-id-123"
    resp = await client.get(
        f"/api/v1/chat/sessions/{uuid.uuid4()}", headers={"X-Request-ID": request_id}
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"] == "Conversation not found"
    assert body["error"]["request_id"] == request_id
    # Back-compat alias the frontend's ApiError reads.
    assert body["detail"] == "Conversation not found"
    assert resp.headers["x-request-id"] == request_id


async def test_request_id_generated_when_absent(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/ping")
    assert resp.status_code == 200
    generated = resp.headers["x-request-id"]
    assert generated and len(generated) == 12  # uuid4 hex, 12 chars


async def test_validation_error_envelope_keeps_detail_list(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/otp/verify", json={"email": "a@b.com", "code": "12"}
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["request_id"]
    # `detail` stays FastAPI's familiar list-of-errors.
    assert isinstance(body["detail"], list)
    assert body["detail"]


async def test_body_size_cap_returns_413_envelope(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "max_request_bytes", 50)
    # A perfectly valid body, but its Content-Length exceeds the (tiny, patched) cap.
    resp = await client.post(
        "/api/v1/auth/otp/verify",
        json={"email": "someone-with-a-long-address@example.com", "code": "123456"},
    )
    assert resp.status_code == 413
    body = resp.json()
    assert body["error"]["code"] == "payload_too_large"
    assert body["error"]["request_id"]
    assert body["detail"]
    assert resp.headers["x-request-id"]


async def test_unhandled_exception_returns_generic_500_and_tails_error_ring() -> None:
    """A route that raises an unexpected error yields a generic 500 envelope (no
    internals leaked) and appends one record to the Redis error ring."""
    from app.main import create_app

    boom_app: FastAPI = create_app()

    @boom_app.get("/api/v1/__boom")
    async def _boom() -> None:
        raise ValueError("secret internal detail")

    transport = httpx.ASGITransport(app=boom_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        resp = await ac.get("/api/v1/__boom", headers={"X-Request-ID": "boom-req-1"})

    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["request_id"] == "boom-req-1"
    # The raised message must never leak to the client.
    assert "secret internal detail" not in resp.text
    assert resp.headers["x-request-id"] == "boom-req-1"

    ring = await get_redis().lrange(ERROR_RING_KEY, 0, -1)
    assert len(ring) == 1
    import orjson

    entry = orjson.loads(ring[0])
    assert entry["request_id"] == "boom-req-1"
    assert entry["path"] == "/api/v1/__boom"
    assert entry["method"] == "GET"
    assert entry["status"] == 500
    assert entry["error_class"] == "ValueError"
