"""Redis-backed refresh session lifecycle: create, rotate, revoke."""

from __future__ import annotations

import pytest

from app.core.security import (
    SessionError,
    TokenType,
    create_session,
    decode_token,
    revoke_session,
    revoke_session_from_refresh_token,
    rotate_session,
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
