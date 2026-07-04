"""Google OAuth callback: real id_token signature/claims verification, mocked network.

Only the two network boundaries (`_fetch_google_token`, `_fetch_google_jwks`) are
monkeypatched; the id_token is a genuinely RSA-signed JWT and `_verify_google_id_token`
performs real signature + issuer/audience validation against it via authlib.jose.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from authlib.jose import JsonWebKey
from authlib.jose import jwt as jose_jwt
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import auth as auth_module
from app.core.config import get_settings
from app.models.identity import User

GOOGLE_CLIENT_ID = "test-google-client-id.apps.googleusercontent.com"


@pytest.fixture
def google_oauth_configured(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", GOOGLE_CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-google-client-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _make_google_key() -> Any:
    return JsonWebKey.generate_key("RSA", 2048, is_private=True, options={"kid": "test-kid"})


def _sign_id_token(
    key: Any, *, sub: str, email: str, name: str, email_verified: bool = True
) -> str:
    now = int(time.time())
    header = {"alg": "RS256", "kid": "test-kid"}
    payload = {
        "iss": "https://accounts.google.com",
        "aud": GOOGLE_CLIENT_ID,
        "sub": sub,
        "email": email,
        "email_verified": email_verified,
        "name": name,
        "iat": now,
        "exp": now + 3600,
    }
    token = jose_jwt.encode(header, payload, key)
    return token.decode() if isinstance(token, bytes) else token


def _decode_state(state_cookie: str) -> str:
    serializer = URLSafeTimedSerializer(get_settings().jwt_secret, salt="oauth-state")
    nonce: str = serializer.loads(state_cookie)
    return nonce


def _mock_google_network(
    monkeypatch: pytest.MonkeyPatch, *, id_token: str, jwks: dict[str, Any]
) -> None:
    async def _fake_fetch_token(code: str) -> dict[str, Any]:
        return {"id_token": id_token, "access_token": "unused"}

    async def _fake_fetch_jwks() -> dict[str, Any]:
        return jwks

    monkeypatch.setattr(auth_module, "_fetch_google_token", _fake_fetch_token)
    monkeypatch.setattr(auth_module, "_fetch_google_jwks", _fake_fetch_jwks)


async def _start_login(client: httpx.AsyncClient) -> str:
    login_resp = await client.get("/api/v1/auth/google", follow_redirects=False)
    state_cookie: str = login_resp.cookies["sarathi_oauth_state"]
    return state_cookie


async def test_google_login_redirects_and_sets_state_cookie(
    client: httpx.AsyncClient, google_oauth_configured: None
) -> None:
    resp = await client.get("/api/v1/auth/google", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "sarathi_oauth_state" in resp.cookies


async def test_google_login_503_when_not_configured(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Empty env vars override any real credentials in the repo-root .env file.
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "")
    get_settings.cache_clear()
    try:
        resp = await client.get("/api/v1/auth/google", follow_redirects=False)
        assert resp.status_code == 503
    finally:
        get_settings.cache_clear()


async def test_google_callback_full_flow_creates_user_and_session(
    client: httpx.AsyncClient,
    google_oauth_configured: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = _make_google_key()
    jwks = {"keys": [key.as_dict(is_private=False)]}
    id_token = _sign_id_token(
        key, sub="google-sub-1", email="new-google-user@example.com", name="Asha Rao"
    )
    _mock_google_network(monkeypatch, id_token=id_token, jwks=jwks)

    state_cookie = await _start_login(client)
    nonce = _decode_state(state_cookie)

    callback_resp = await client.get(
        "/api/v1/auth/google/callback",
        params={"code": "auth-code-123", "state": nonce},
        follow_redirects=False,
        cookies={"sarathi_oauth_state": state_cookie},
    )
    assert callback_resp.status_code == 302
    assert callback_resp.headers["location"].endswith("/app/home")
    assert "sarathi_access" in callback_resp.cookies
    assert "sarathi_refresh" in callback_resp.cookies

    me_resp = await client.get("/api/v1/me")
    assert me_resp.status_code == 200
    body = me_resp.json()
    assert body["user"]["email"] == "new-google-user@example.com"
    assert body["customer"]["full_name"] == "Asha Rao"


async def test_google_callback_rejects_state_mismatch(
    client: httpx.AsyncClient, google_oauth_configured: None
) -> None:
    state_cookie = await _start_login(client)

    resp = await client.get(
        "/api/v1/auth/google/callback",
        params={"code": "some-code", "state": "not-the-real-nonce"},
        follow_redirects=False,
        cookies={"sarathi_oauth_state": state_cookie},
    )
    assert resp.status_code == 400


async def test_google_callback_rejects_unverified_email(
    client: httpx.AsyncClient,
    google_oauth_configured: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = _make_google_key()
    jwks = {"keys": [key.as_dict(is_private=False)]}
    id_token = _sign_id_token(
        key,
        sub="google-sub-2",
        email="unverified@example.com",
        name="Someone",
        email_verified=False,
    )
    _mock_google_network(monkeypatch, id_token=id_token, jwks=jwks)

    state_cookie = await _start_login(client)
    nonce = _decode_state(state_cookie)

    resp = await client.get(
        "/api/v1/auth/google/callback",
        params={"code": "code", "state": nonce},
        follow_redirects=False,
        cookies={"sarathi_oauth_state": state_cookie},
    )
    assert resp.status_code == 400


async def test_google_callback_rejects_bad_signature(
    client: httpx.AsyncClient,
    google_oauth_configured: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A token signed by a *different* key than what the (mocked) JWKS advertises."""
    real_key = _make_google_key()
    attacker_key = _make_google_key()
    jwks = {"keys": [real_key.as_dict(is_private=False)]}
    id_token = _sign_id_token(
        attacker_key, sub="google-sub-3", email="victim@example.com", name="Victim"
    )
    _mock_google_network(monkeypatch, id_token=id_token, jwks=jwks)

    state_cookie = await _start_login(client)
    nonce = _decode_state(state_cookie)

    resp = await client.get(
        "/api/v1/auth/google/callback",
        params={"code": "code", "state": nonce},
        follow_redirects=False,
        cookies={"sarathi_oauth_state": state_cookie},
    )
    assert resp.status_code == 400


async def test_google_callback_links_existing_user_by_verified_email(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    google_oauth_configured: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing (e.g. OTP-created) user with no `google_sub` gets linked, not duplicated."""
    email = "already-here@example.com"
    existing_user = User(email=email)
    db_session.add(existing_user)
    await db_session.flush()
    existing_user_id = existing_user.id
    assert existing_user.google_sub is None

    key = _make_google_key()
    jwks = {"keys": [key.as_dict(is_private=False)]}
    id_token = _sign_id_token(key, sub="google-sub-link", email=email, name="Already Here")
    _mock_google_network(monkeypatch, id_token=id_token, jwks=jwks)

    state_cookie = await _start_login(client)
    nonce = _decode_state(state_cookie)

    callback_resp = await client.get(
        "/api/v1/auth/google/callback",
        params={"code": "code", "state": nonce},
        follow_redirects=False,
        cookies={"sarathi_oauth_state": state_cookie},
    )
    assert callback_resp.status_code == 302

    me_resp = await client.get("/api/v1/me")
    assert me_resp.status_code == 200
    assert me_resp.json()["user"]["id"] == str(existing_user_id)

    await db_session.refresh(existing_user)
    assert existing_user.google_sub == "google-sub-link"
