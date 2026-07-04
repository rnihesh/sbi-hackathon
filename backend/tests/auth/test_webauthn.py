"""Passkey registration + login round trip, driven by the real HTTP routes.

`FakeAuthenticator` (tests/auth/fake_authenticator.py) performs real ES256 signing; the
server-side verification is the genuine `py_webauthn` code path — nothing about the
crypto/verification is mocked, only the "browser + hardware key" is simulated.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from webauthn import base64url_to_bytes

from app.services import email as email_service
from tests.auth.fake_authenticator import FakeAuthenticator

ORIGIN = "http://localhost:3000"  # matches Settings.webauthn_origin default


@pytest.fixture(autouse=True)
def _mock_email_send(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def _fake_send_templated(
        to: str, template_name: str, context: dict[str, Any]
    ) -> email_service.EmailResult:
        sent.append({"to": to, "template_name": template_name, "context": context})
        return email_service.EmailResult(sent=True, message_id="test-message-id")

    monkeypatch.setattr("app.api.v1.auth.send_templated", _fake_send_templated)
    return sent


async def _login_via_otp(
    client: httpx.AsyncClient, mock_email_send: list[dict[str, Any]], email: str
) -> None:
    await client.post("/api/v1/auth/otp/send", json={"email": email})
    code = mock_email_send[-1]["context"]["code"]
    resp = await client.post("/api/v1/auth/otp/verify", json={"email": email, "code": code})
    assert resp.status_code == 200


async def test_passkey_register_requires_auth(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/passkey/register/begin")
    assert resp.status_code == 401


async def test_passkey_register_and_login_round_trip(
    client: httpx.AsyncClient, _mock_email_send: list[dict[str, Any]]
) -> None:
    email = "passkey-user@example.com"
    await _login_via_otp(client, _mock_email_send, email)

    # --- register ---
    begin_resp = await client.post("/api/v1/auth/passkey/register/begin")
    assert begin_resp.status_code == 200
    options = begin_resp.json()
    challenge = base64url_to_bytes(options["challenge"])

    authenticator = FakeAuthenticator.generate(credential_id=b"cred-0000000001")
    credential = authenticator.registration_response(
        challenge=challenge, rp_id=options["rp"]["id"], origin=ORIGIN
    )

    complete_resp = await client.post(
        "/api/v1/auth/passkey/register/complete",
        json={"credential": credential, "label": "Test key"},
    )
    assert complete_resp.status_code == 200
    body = complete_resp.json()
    assert body["label"] == "Test key"
    assert body["transport"] == "platform"

    # --- log out, then log back in with only the passkey ---
    await client.post("/api/v1/auth/logout")
    me_after_logout = await client.get("/api/v1/me")
    assert me_after_logout.status_code == 401

    login_begin_resp = await client.post(
        "/api/v1/auth/passkey/login/begin", json={"email": email}
    )
    assert login_begin_resp.status_code == 200
    login_options = login_begin_resp.json()
    login_challenge = base64url_to_bytes(login_options["challenge"])

    assertion = authenticator.authentication_response(
        challenge=login_challenge, rp_id=login_options["rpId"], origin=ORIGIN
    )
    login_complete_resp = await client.post(
        "/api/v1/auth/passkey/login/complete", json={"credential": assertion}
    )
    assert login_complete_resp.status_code == 200
    assert login_complete_resp.json()["user"]["email"] == email
    assert "sarathi_access" in login_complete_resp.cookies

    me_resp = await client.get("/api/v1/me")
    assert me_resp.status_code == 200
    assert me_resp.json()["user"]["email"] == email


async def test_passkey_login_discoverable_without_email(
    client: httpx.AsyncClient, _mock_email_send: list[dict[str, Any]]
) -> None:
    email = "discoverable-user@example.com"
    await _login_via_otp(client, _mock_email_send, email)

    begin_resp = await client.post("/api/v1/auth/passkey/register/begin")
    options = begin_resp.json()
    authenticator = FakeAuthenticator.generate(credential_id=b"cred-discoverable1")
    credential = authenticator.registration_response(
        challenge=base64url_to_bytes(options["challenge"]), rp_id=options["rp"]["id"], origin=ORIGIN
    )
    await client.post(
        "/api/v1/auth/passkey/register/complete", json={"credential": credential}
    )
    await client.post("/api/v1/auth/logout")

    # no email in the body: usernameless/discoverable challenge
    login_begin_resp = await client.post("/api/v1/auth/passkey/login/begin", json={})
    assert login_begin_resp.status_code == 200
    login_options = login_begin_resp.json()
    assert login_options.get("allowCredentials") in (None, [])

    assertion = authenticator.authentication_response(
        challenge=base64url_to_bytes(login_options["challenge"]),
        rp_id=login_options["rpId"],
        origin=ORIGIN,
    )
    login_complete_resp = await client.post(
        "/api/v1/auth/passkey/login/complete", json={"credential": assertion}
    )
    assert login_complete_resp.status_code == 200
    assert login_complete_resp.json()["user"]["email"] == email


async def test_passkey_login_unknown_credential_is_rejected(client: httpx.AsyncClient) -> None:
    stray = FakeAuthenticator.generate(credential_id=b"never-registered-01")
    begin_resp = await client.post("/api/v1/auth/passkey/login/begin", json={})
    options = begin_resp.json()
    assertion = stray.authentication_response(
        challenge=base64url_to_bytes(options["challenge"]),
        rp_id=options["rpId"],
        origin=ORIGIN,
    )
    resp = await client.post("/api/v1/auth/passkey/login/complete", json={"credential": assertion})
    assert resp.status_code == 401


async def test_passkey_login_replayed_challenge_is_rejected(
    client: httpx.AsyncClient, _mock_email_send: list[dict[str, Any]]
) -> None:
    email = "replay-user@example.com"
    await _login_via_otp(client, _mock_email_send, email)

    begin_resp = await client.post("/api/v1/auth/passkey/register/begin")
    options = begin_resp.json()
    authenticator = FakeAuthenticator.generate(credential_id=b"cred-replay-000001")
    credential = authenticator.registration_response(
        challenge=base64url_to_bytes(options["challenge"]), rp_id=options["rp"]["id"], origin=ORIGIN
    )
    await client.post("/api/v1/auth/passkey/register/complete", json={"credential": credential})

    login_begin_resp = await client.post(
        "/api/v1/auth/passkey/login/begin", json={"email": email}
    )
    login_options = login_begin_resp.json()
    assertion = authenticator.authentication_response(
        challenge=base64url_to_bytes(login_options["challenge"]),
        rp_id=login_options["rpId"],
        origin=ORIGIN,
    )

    first = await client.post("/api/v1/auth/passkey/login/complete", json={"credential": assertion})
    assert first.status_code == 200

    # replaying the exact same assertion must fail: the challenge was consumed
    second = await client.post(
        "/api/v1/auth/passkey/login/complete", json={"credential": assertion}
    )
    assert second.status_code == 400


async def test_passkey_register_excludes_existing_credentials(
    client: httpx.AsyncClient, _mock_email_send: list[dict[str, Any]]
) -> None:
    email = "exclude-user@example.com"
    await _login_via_otp(client, _mock_email_send, email)

    begin_resp = await client.post("/api/v1/auth/passkey/register/begin")
    options = begin_resp.json()
    authenticator = FakeAuthenticator.generate(credential_id=b"cred-exclude-0001")
    credential = authenticator.registration_response(
        challenge=base64url_to_bytes(options["challenge"]), rp_id=options["rp"]["id"], origin=ORIGIN
    )
    await client.post("/api/v1/auth/passkey/register/complete", json={"credential": credential})

    second_begin_resp = await client.post("/api/v1/auth/passkey/register/begin")
    second_options = second_begin_resp.json()
    exclude_ids = {c["id"] for c in second_options.get("excludeCredentials", [])}
    assert credential["id"] in exclude_ids
