"""Rate-limit dependency + 429 envelope tests.

The :func:`app.core.ratelimit.rate_limit` factory is exercised directly against a
real (flushed-per-test) Redis logical DB with hand-built Request objects - no LLM,
no heavy endpoint - so enforcement, window reset, per-key isolation, and the
user-vs-ip key strategy are all covered cheaply and deterministically. One
integration test drives the real ``/auth/otp/send`` per-IP limit end to end to
prove the 429 envelope + ``Retry-After`` header wiring.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from starlette.requests import Request

from app.core.ratelimit import RateLimitExceeded, rate_limit
from app.core.redis import get_redis
from app.core.security import ACCESS_COOKIE, create_access_token

pytestmark = pytest.mark.anyio


def _make_request(
    *,
    client_host: str = "1.2.3.4",
    cookies: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> Request:
    raw_headers: list[tuple[bytes, bytes]] = []
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode(), value.encode()))
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        raw_headers.append((b"cookie", cookie_str.encode()))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "query_string": b"",
        "headers": raw_headers,
        "client": (client_host, 12345),
        "scheme": "http",
        "server": ("testserver", 80),
    }
    return Request(scope)


async def test_rate_limit_enforced_and_sets_ttl() -> None:
    dep = rate_limit("t_enforce", limit=2, window_seconds=60, key="by_ip")
    request = _make_request()

    await dep(request)  # 1
    await dep(request)  # 2 (at the limit, still allowed)

    # First hit stamped a TTL that will expire the whole window.
    ttl = await get_redis().ttl("ratelimit:t_enforce:ip:1.2.3.4")
    assert 0 < ttl <= 60

    with pytest.raises(RateLimitExceeded) as excinfo:
        await dep(request)  # 3 - over budget
    assert excinfo.value.retry_after_seconds >= 1
    assert excinfo.value.name == "t_enforce"


async def test_rate_limit_per_key_isolation() -> None:
    dep = rate_limit("t_iso", limit=1, window_seconds=60, key="by_ip")

    await dep(_make_request(client_host="10.0.0.1"))
    with pytest.raises(RateLimitExceeded):
        await dep(_make_request(client_host="10.0.0.1"))

    # A different IP has its own, untouched budget.
    await dep(_make_request(client_host="10.0.0.2"))


async def test_rate_limit_window_resets() -> None:
    dep = rate_limit("t_reset", limit=1, window_seconds=1, key="by_ip")
    request = _make_request(client_host="9.9.9.9")

    await dep(request)
    with pytest.raises(RateLimitExceeded):
        await dep(request)

    # Fixed window: once the 1s TTL elapses the counter is gone and calls flow again.
    await asyncio.sleep(1.2)
    await dep(request)  # must not raise


async def test_rate_limit_by_user_keys_on_token_not_ip() -> None:
    dep = rate_limit("t_user", limit=1, window_seconds=60, key="by_user")
    token_a = create_access_token("11111111-1111-1111-1111-111111111111")
    token_b = create_access_token("22222222-2222-2222-2222-222222222222")

    # Two users share one IP but get independent budgets (keyed on the JWT subject).
    await dep(_make_request(cookies={ACCESS_COOKIE: token_a}))
    with pytest.raises(RateLimitExceeded):
        await dep(_make_request(cookies={ACCESS_COOKIE: token_a}))
    await dep(_make_request(cookies={ACCESS_COOKIE: token_b}))  # different user, allowed

    # An anonymous caller (no cookie) falls back to the IP bucket.
    await dep(_make_request(client_host="5.5.5.5"))
    with pytest.raises(RateLimitExceeded):
        await dep(_make_request(client_host="5.5.5.5"))


async def test_otp_send_per_ip_limit_returns_429_envelope(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The per-IP OTP cap (30/hour) trips a real 429 with the structured
    envelope + retry metadata, distinct from the handler's generic 200."""
    from app.services import email as email_service

    async def _no_send(to: str, template_name: str, context: dict[str, object]) -> object:
        return email_service.EmailResult(sent=True, message_id="test")

    monkeypatch.setattr("app.api.v1.auth.send_templated", _no_send)

    # Distinct emails so the per-email (3/hour) limit never masks the per-IP limit.
    for i in range(30):
        resp = await client.post(
            "/api/v1/auth/otp/send", json={"email": f"iprate{i}@example.com"}
        )
        assert resp.status_code == 200

    blocked = await client.post("/api/v1/auth/otp/send", json={"email": "iprate-over@example.com"})
    assert blocked.status_code == 429
    body = blocked.json()
    assert body["error"]["code"] == "rate_limited"
    assert body["error"]["request_id"]
    assert body["detail"]  # top-level alias present for the frontend
    assert body["retry_after_seconds"] >= 1
    assert blocked.headers["retry-after"] == str(body["retry_after_seconds"])
    assert blocked.headers["x-request-id"]
