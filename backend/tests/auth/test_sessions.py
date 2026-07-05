"""Redis-backed refresh session lifecycle: create, rotate, revoke, list, and the
device/IP/timing metadata each session key now carries (the security surface's
data model)."""

from __future__ import annotations

import json

import pytest

from app.core.redis import get_redis
from app.core.security import (
    SessionError,
    TokenType,
    create_session,
    decode_token,
    jti_suffix,
    list_sessions,
    revoke_session,
    revoke_session_from_refresh_token,
    rotate_session,
    summarize_user_agent,
)

_CHROME_MAC_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_SAFARI_IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


async def test_create_session_issues_valid_pair() -> None:
    access, refresh = await create_session("user-1")
    access_payload = decode_token(access, expected_type=TokenType.ACCESS)
    refresh_payload = decode_token(refresh, expected_type=TokenType.REFRESH)
    assert access_payload["sub"] == "user-1"
    assert refresh_payload["sub"] == "user-1"
    assert "jti" in refresh_payload


async def test_rotate_session_issues_new_pair_and_revokes_old_jti() -> None:
    _, refresh1 = await create_session("user-2")
    old_payload = decode_token(refresh1, expected_type=TokenType.REFRESH)

    _, refresh2 = await rotate_session(refresh1)
    new_payload = decode_token(refresh2, expected_type=TokenType.REFRESH)

    assert new_payload["jti"] != old_payload["jti"]

    # replaying the (now-revoked) old refresh token must fail
    with pytest.raises(SessionError):
        await rotate_session(refresh1)


async def test_rotate_session_rejects_malformed_token() -> None:
    with pytest.raises(SessionError):
        await rotate_session("not-a-real-jwt")


async def test_revoke_session_makes_rotation_fail() -> None:
    _, refresh = await create_session("user-3")
    payload = decode_token(refresh, expected_type=TokenType.REFRESH)
    await revoke_session("user-3", payload["jti"])
    with pytest.raises(SessionError):
        await rotate_session(refresh)


async def test_revoke_session_is_idempotent() -> None:
    _, refresh = await create_session("user-3b")
    payload = decode_token(refresh, expected_type=TokenType.REFRESH)
    await revoke_session("user-3b", payload["jti"])
    await revoke_session("user-3b", payload["jti"])  # must not raise


async def test_revoke_session_from_refresh_token_then_rotation_fails() -> None:
    _, refresh = await create_session("user-4")
    await revoke_session_from_refresh_token(refresh)
    with pytest.raises(SessionError):
        await rotate_session(refresh)


async def test_revoke_session_from_refresh_token_never_raises_on_garbage() -> None:
    # Logout must always succeed, even with a missing/expired/malformed cookie value.
    await revoke_session_from_refresh_token("garbage")
    await revoke_session_from_refresh_token("")


async def test_two_sessions_for_same_user_are_independent() -> None:
    _, refresh_a = await create_session("user-5")
    _, refresh_b = await create_session("user-5")

    await revoke_session_from_refresh_token(refresh_a)

    with pytest.raises(SessionError):
        await rotate_session(refresh_a)
    # session b is untouched
    await rotate_session(refresh_b)


# --- session metadata (device/IP/timing) ---------------------------------------------


async def test_summarize_user_agent_parses_browser_and_os() -> None:
    assert summarize_user_agent(_CHROME_MAC_UA, fallback="Unknown device") == "Chrome on Mac"
    assert summarize_user_agent(_SAFARI_IPHONE_UA, fallback="Unknown device") == "Safari on iPhone"


async def test_summarize_user_agent_falls_back_for_missing_ua() -> None:
    assert summarize_user_agent(None, fallback="Unknown device") == "Unknown device"
    assert summarize_user_agent("", fallback="Passkey") == "Passkey"


async def test_create_session_stores_device_ip_and_timing_metadata() -> None:
    _, refresh = await create_session(
        "user-meta-1", user_agent=_CHROME_MAC_UA, ip="203.0.113.42"
    )
    payload = decode_token(refresh, expected_type=TokenType.REFRESH)

    sessions = await list_sessions("user-meta-1")
    assert len(sessions) == 1
    info = sessions[0]
    assert info.jti == payload["jti"]
    assert info.device == "Chrome on Mac"
    assert info.ip_prefix == "203.0.113.0/24"
    assert info.created_at is not None
    assert info.last_seen_at is not None


async def test_create_session_handles_missing_ua_and_ip() -> None:
    await create_session("user-meta-2")
    sessions = await list_sessions("user-meta-2")
    assert sessions[0].device == "Unknown device"
    assert sessions[0].ip_prefix is None


async def test_list_sessions_reports_legacy_session_as_unknown_device() -> None:
    """A session created before the metadata upgrade stored a bare ``"1"`` marker.
    It must still list (not error), with no device/timestamps on file."""
    redis = get_redis()
    await redis.set("session:user-legacy:some-jti-123456", "1", ex=3600)

    sessions = await list_sessions("user-legacy")
    assert len(sessions) == 1
    assert sessions[0].jti == "some-jti-123456"
    assert sessions[0].device is None
    assert sessions[0].created_at is None
    assert sessions[0].last_seen_at is None


async def test_list_sessions_ignores_garbage_json_the_same_as_legacy() -> None:
    redis = get_redis()
    await redis.set("session:user-garbage:jti-abcdef", "{not json", ex=3600)
    sessions = await list_sessions("user-garbage")
    assert sessions[0].device is None


async def test_rotate_session_carries_created_at_forward_and_refreshes_device() -> None:
    _, refresh1 = await create_session("user-meta-3", user_agent=_CHROME_MAC_UA)
    original_created_at = (await list_sessions("user-meta-3"))[0].created_at

    _, refresh2 = await rotate_session(refresh1, user_agent=_SAFARI_IPHONE_UA, ip="198.51.100.7")

    sessions = await list_sessions("user-meta-3")
    assert len(sessions) == 1  # old jti was revoked, replaced by the new one
    rotated = sessions[0]
    new_payload = decode_token(refresh2, expected_type=TokenType.REFRESH)
    assert rotated.jti == new_payload["jti"]
    # created_at is carried forward from the original session, not reset...
    assert rotated.created_at == original_created_at
    # ...while device/IP reflect *this* rotation's request.
    assert rotated.device == "Safari on iPhone"
    assert rotated.ip_prefix == "198.51.100.0/24"


async def test_rotate_session_from_legacy_session_upgrades_without_created_at() -> None:
    """Rotating a pre-upgrade (bare "1") session has no original creation time to
    carry forward - it defaults to now, the one documented compatibility gap."""
    redis = get_redis()
    user_id = "user-legacy-rotate"
    # Mint a real refresh token/jti pair, then downgrade its Redis value to the
    # legacy marker to simulate a session that predates the metadata upgrade.
    _, refresh = await create_session(user_id)
    payload = decode_token(refresh, expected_type=TokenType.REFRESH)
    await redis.set(f"session:{user_id}:{payload['jti']}", "1", ex=3600)

    await rotate_session(refresh, user_agent=_CHROME_MAC_UA)

    sessions = await list_sessions(user_id)
    assert len(sessions) == 1
    assert sessions[0].device == "Chrome on Mac"
    assert sessions[0].created_at is not None  # defaulted to "now", not lost/erroring


async def test_list_sessions_scoped_to_user() -> None:
    await create_session("user-scope-a")
    await create_session("user-scope-b")
    sessions_a = await list_sessions("user-scope-a")
    assert len(sessions_a) == 1
    assert all(s.jti for s in sessions_a)


async def test_list_sessions_empty_for_unknown_user() -> None:
    assert await list_sessions("nobody-has-this-id") == []


async def test_jti_suffix_is_last_six_characters() -> None:
    _, refresh = await create_session("user-suffix")
    payload = decode_token(refresh, expected_type=TokenType.REFRESH)
    jti = payload["jti"]
    assert jti_suffix(jti) == jti[-6:]
    assert len(jti_suffix(jti)) == 6


async def test_session_value_round_trips_as_json_not_bare_marker() -> None:
    """Documents the upgraded Redis value shape directly (guards against a future
    change accidentally reverting to the bare "1" marker)."""
    _, refresh = await create_session("user-json-shape", user_agent=_CHROME_MAC_UA)
    payload = decode_token(refresh, expected_type=TokenType.REFRESH)
    raw = await get_redis().get(f"session:user-json-shape:{payload['jti']}")
    assert raw is not None
    assert raw != "1"
    parsed = json.loads(raw)
    assert parsed["device"] == "Chrome on Mac"
    assert "created_at" in parsed and "last_seen_at" in parsed
