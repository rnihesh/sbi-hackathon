"""``GET``/``DELETE /auth/sessions`` - the active-sessions security surface.

Sessions are seeded directly via ``create_session`` (rather than a full OTP/passkey
login round trip - already covered by test_otp.py/test_webauthn.py) so each test can
freely control how many "devices" a user has and which one is "current".
"""

from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.core.security import TokenType, create_session, decode_token
from app.models.identity import User

_CHROME_MAC_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_SAFARI_IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


async def _user(db_session: AsyncSession, email: str) -> User:
    user = User(email=email)
    db_session.add(user)
    await db_session.flush()
    return user


def _cookies(access: str, refresh: str) -> dict[str, str]:
    return {"sarathi_access": access, "sarathi_refresh": refresh}


async def test_list_sessions_marks_the_calling_cookie_as_current(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user(db_session, "sessions-list@example.com")
    access, refresh = await create_session(str(user.id), user_agent=_CHROME_MAC_UA)

    resp = await client.get("/api/v1/auth/sessions", cookies=_cookies(access, refresh))

    assert resp.status_code == 200
    sessions = resp.json()
    assert len(sessions) == 1
    assert sessions[0]["current"] is True
    assert sessions[0]["device"] == "Chrome on Mac"
    assert sessions[0]["created_at"] is not None
    assert len(sessions[0]["jti_suffix"]) == 6
    # The full jti must never leak into the response.
    full_jti = decode_token(refresh, expected_type=TokenType.REFRESH)["jti"]
    assert full_jti not in resp.text


async def test_list_sessions_shows_other_devices_as_not_current(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user(db_session, "sessions-multi@example.com")
    access1, refresh1 = await create_session(str(user.id), user_agent=_CHROME_MAC_UA)
    await create_session(str(user.id), user_agent=_SAFARI_IPHONE_UA)

    resp = await client.get("/api/v1/auth/sessions", cookies=_cookies(access1, refresh1))

    assert resp.status_code == 200
    sessions = resp.json()
    assert len(sessions) == 2
    current = [s for s in sessions if s["current"]]
    other = [s for s in sessions if not s["current"]]
    assert len(current) == 1
    assert len(other) == 1
    assert other[0]["device"] == "Safari on iPhone"


async def test_list_sessions_requires_auth(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/sessions")
    assert resp.status_code == 401


async def test_revoke_other_device_session_makes_its_refresh_fail(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user(db_session, "sessions-revoke-other@example.com")
    access1, refresh1 = await create_session(str(user.id), user_agent=_CHROME_MAC_UA)
    _access2, refresh2 = await create_session(str(user.id), user_agent=_SAFARI_IPHONE_UA)

    list_resp = await client.get("/api/v1/auth/sessions", cookies=_cookies(access1, refresh1))
    other = next(s for s in list_resp.json() if not s["current"])

    revoke_resp = await client.delete(
        f"/api/v1/auth/sessions/{other['jti_suffix']}", cookies=_cookies(access1, refresh1)
    )
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["message"] == "session revoked"

    # The revoked (other-device) refresh token can no longer rotate.
    refresh_resp = await client.post("/api/v1/auth/refresh", cookies={"sarathi_refresh": refresh2})
    assert refresh_resp.status_code == 401

    # The calling (current) session is untouched.
    still_listed = await client.get("/api/v1/auth/sessions", cookies=_cookies(access1, refresh1))
    assert still_listed.status_code == 200
    assert len(still_listed.json()) == 1


async def test_revoke_current_session_clears_cookies_and_is_logout(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user(db_session, "sessions-revoke-current@example.com")
    access, refresh = await create_session(str(user.id), user_agent=_CHROME_MAC_UA)

    list_resp = await client.get("/api/v1/auth/sessions", cookies=_cookies(access, refresh))
    suffix = list_resp.json()[0]["jti_suffix"]

    revoke_resp = await client.delete(
        f"/api/v1/auth/sessions/{suffix}", cookies=_cookies(access, refresh)
    )
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["message"] == "logged out"

    set_cookie_headers = revoke_resp.headers.get_list("set-cookie")
    assert any("sarathi_access=" in h for h in set_cookie_headers)
    assert any("sarathi_refresh=" in h for h in set_cookie_headers)

    # The revoked session's own refresh token can no longer rotate.
    refresh_resp = await client.post("/api/v1/auth/refresh", cookies={"sarathi_refresh": refresh})
    assert refresh_resp.status_code == 401


async def test_revoke_unknown_suffix_is_404(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    user = await _user(db_session, "sessions-404@example.com")
    access, refresh = await create_session(str(user.id))

    resp = await client.delete("/api/v1/auth/sessions/zzzzzz", cookies=_cookies(access, refresh))
    assert resp.status_code == 404


async def test_revoke_ambiguous_suffix_is_409(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """Craft a genuine jti-suffix collision directly in Redis - real jtis have
    enough entropy that this essentially never happens on its own, so the 409 path
    needs to be exercised deterministically rather than relying on chance."""
    user = await _user(db_session, "sessions-409@example.com")
    access, refresh = await create_session(str(user.id))
    real_jti = decode_token(refresh, expected_type=TokenType.REFRESH)["jti"]
    suffix = real_jti[-6:]

    redis = get_redis()
    colliding_jti = f"deliberately-colliding-{suffix}"
    await redis.set(
        f"session:{user.id}:{colliding_jti}",
        '{"device": "Firefox on Windows"}',
        ex=3600,
    )

    resp = await client.delete(f"/api/v1/auth/sessions/{suffix}", cookies=_cookies(access, refresh))
    assert resp.status_code == 409

    # Neither session was touched by the ambiguous request.
    list_resp = await client.get("/api/v1/auth/sessions", cookies=_cookies(access, refresh))
    assert len(list_resp.json()) == 2
