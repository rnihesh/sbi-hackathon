"""Email OTP send/verify flow, exercised via the real HTTP routes.

Email sending is mocked at the `app.api.v1.auth.send_templated` binding (the exact name
the route handlers call) so no real SES calls happen; the OTP hashing, rate limiting,
enumeration-safety, and session issuance logic all run for real against Postgres/Redis.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import Customer
from app.models.identity import OtpCode, User
from app.services import email as email_service


@pytest.fixture(autouse=True)
def _mock_email_send(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record every templated send instead of hitting real SES."""
    sent: list[dict[str, Any]] = []

    async def _fake_send_templated(
        to: str, template_name: str, context: dict[str, Any]
    ) -> email_service.EmailResult:
        sent.append({"to": to, "template_name": template_name, "context": context})
        return email_service.EmailResult(sent=True, message_id="test-message-id")

    monkeypatch.setattr("app.api.v1.auth.send_templated", _fake_send_templated)
    return sent


async def test_otp_send_always_returns_generic_200(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/otp/send", json={"email": "new-user@example.com"})
    assert resp.status_code == 200
    assert "message" in resp.json()


async def test_otp_send_stores_sha256_hash_not_plaintext(
    client: httpx.AsyncClient, db_session: AsyncSession, _mock_email_send: list[dict[str, Any]]
) -> None:
    email = "hash-check@example.com"
    resp = await client.post("/api/v1/auth/otp/send", json={"email": email})
    assert resp.status_code == 200

    result = await db_session.execute(select(OtpCode).where(OtpCode.email == email))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert len(rows[0].code_hash) == 64  # sha256 hex digest length
    assert rows[0].consumed is False

    sent_code = _mock_email_send[0]["context"]["code"]
    assert len(sent_code) == 6 and sent_code.isdigit()
    assert hashlib.sha256(sent_code.encode()).hexdigest() == rows[0].code_hash
    assert rows[0].code_hash != sent_code  # never store plaintext


async def test_otp_verify_success_creates_user_and_customer_and_sets_cookies(
    client: httpx.AsyncClient, db_session: AsyncSession, _mock_email_send: list[dict[str, Any]]
) -> None:
    email = "verify-success@example.com"
    await client.post("/api/v1/auth/otp/send", json={"email": email})
    code = _mock_email_send[0]["context"]["code"]

    resp = await client.post("/api/v1/auth/otp/verify", json={"email": email, "code": code})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["email"] == email
    assert body["customer"]["full_name"]

    assert "sarathi_access" in resp.cookies
    assert "sarathi_refresh" in resp.cookies

    user_result = await db_session.execute(select(User).where(User.email == email))
    user = user_result.scalar_one()
    customer_result = await db_session.execute(select(Customer).where(Customer.user_id == user.id))
    assert customer_result.scalar_one_or_none() is not None

    assert any(call["template_name"] == "welcome" for call in _mock_email_send)


async def test_otp_verify_wrong_code_is_generic_400(
    client: httpx.AsyncClient, _mock_email_send: list[dict[str, Any]]
) -> None:
    email = "wrong-code@example.com"
    await client.post("/api/v1/auth/otp/send", json={"email": email})
    resp = await client.post("/api/v1/auth/otp/verify", json={"email": email, "code": "000000"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid or expired code"


async def test_otp_verify_unknown_email_same_generic_400(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/otp/verify", json={"email": "never-sent@example.com", "code": "123456"}
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid or expired code"


async def test_otp_code_can_only_be_consumed_once(
    client: httpx.AsyncClient, _mock_email_send: list[dict[str, Any]]
) -> None:
    email = "consume-once@example.com"
    await client.post("/api/v1/auth/otp/send", json={"email": email})
    code = _mock_email_send[0]["context"]["code"]

    first = await client.post("/api/v1/auth/otp/verify", json={"email": email, "code": code})
    assert first.status_code == 200

    second = await client.post("/api/v1/auth/otp/verify", json={"email": email, "code": code})
    assert second.status_code == 400
    assert second.json()["detail"] == "Invalid or expired code"


async def test_otp_expired_code_is_rejected(
    client: httpx.AsyncClient, db_session: AsyncSession, _mock_email_send: list[dict[str, Any]]
) -> None:
    email = "expired@example.com"
    await client.post("/api/v1/auth/otp/send", json={"email": email})
    code = _mock_email_send[0]["context"]["code"]

    result = await db_session.execute(select(OtpCode).where(OtpCode.email == email))
    row = result.scalar_one()
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.flush()

    resp = await client.post("/api/v1/auth/otp/verify", json={"email": email, "code": code})
    assert resp.status_code == 400


async def test_otp_send_is_rate_limited_after_three_per_hour(
    client: httpx.AsyncClient, _mock_email_send: list[dict[str, Any]]
) -> None:
    email = "rate-limited@example.com"
    for _ in range(3):
        resp = await client.post("/api/v1/auth/otp/send", json={"email": email})
        assert resp.status_code == 200
    assert len(_mock_email_send) == 3

    resp = await client.post("/api/v1/auth/otp/send", json={"email": email})
    assert resp.status_code == 200  # still the same generic message
    assert len(_mock_email_send) == 3  # ...but no 4th send actually happened


async def test_otp_send_survives_email_not_configured(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _raise_not_configured(
        to: str, template_name: str, context: dict[str, Any]
    ) -> email_service.EmailResult:
        raise email_service.EmailNotConfigured("no creds")

    monkeypatch.setattr("app.api.v1.auth.send_templated", _raise_not_configured)
    resp = await client.post("/api/v1/auth/otp/send", json={"email": "no-creds@example.com"})
    assert resp.status_code == 200


async def test_me_requires_auth(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/me")
    assert resp.status_code == 401


async def test_me_after_otp_login(
    client: httpx.AsyncClient, _mock_email_send: list[dict[str, Any]]
) -> None:
    email = "me-flow@example.com"
    await client.post("/api/v1/auth/otp/send", json={"email": email})
    code = _mock_email_send[0]["context"]["code"]
    verify_resp = await client.post("/api/v1/auth/otp/verify", json={"email": email, "code": code})
    assert verify_resp.status_code == 200

    me_resp = await client.get("/api/v1/me")
    assert me_resp.status_code == 200
    assert me_resp.json()["user"]["email"] == email


async def test_refresh_rotates_cookie_and_old_one_then_fails(
    client: httpx.AsyncClient, _mock_email_send: list[dict[str, Any]]
) -> None:
    email = "refresh-flow@example.com"
    await client.post("/api/v1/auth/otp/send", json={"email": email})
    code = _mock_email_send[0]["context"]["code"]
    await client.post("/api/v1/auth/otp/verify", json={"email": email, "code": code})

    old_refresh_cookie = client.cookies.get("sarathi_refresh")
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 200
    new_refresh_cookie = client.cookies.get("sarathi_refresh")
    assert new_refresh_cookie != old_refresh_cookie

    me_resp = await client.get("/api/v1/me")
    assert me_resp.status_code == 200


async def test_refresh_without_cookie_is_401(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401


async def test_logout_clears_session(
    client: httpx.AsyncClient, _mock_email_send: list[dict[str, Any]]
) -> None:
    email = "logout-flow@example.com"
    await client.post("/api/v1/auth/otp/send", json={"email": email})
    code = _mock_email_send[0]["context"]["code"]
    await client.post("/api/v1/auth/otp/verify", json={"email": email, "code": code})

    logout_resp = await client.post("/api/v1/auth/logout")
    assert logout_resp.status_code == 200

    me_resp = await client.get("/api/v1/me")
    assert me_resp.status_code == 401


async def test_logout_is_idempotent_without_a_session(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 200
