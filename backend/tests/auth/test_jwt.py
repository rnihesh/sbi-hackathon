"""JWT mint/verify lifecycle tests (no DB/network)."""

from __future__ import annotations

import time

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import (
    TokenError,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
)


def test_access_token_round_trips() -> None:
    token = create_access_token("user-123")
    payload = decode_token(token, expected_type=TokenType.ACCESS)
    assert payload["sub"] == "user-123"
    assert payload["type"] == "access"


def test_refresh_token_round_trips_with_extra_claims() -> None:
    token = create_refresh_token("user-123", jti="abc")
    payload = decode_token(token, expected_type=TokenType.REFRESH)
    assert payload["jti"] == "abc"
    assert payload["type"] == "refresh"


def test_decode_rejects_wrong_type() -> None:
    token = create_access_token("user-123")
    with pytest.raises(TokenError):
        decode_token(token, expected_type=TokenType.REFRESH)


def test_decode_rejects_expired_token() -> None:
    settings = get_settings()
    now = int(time.time())
    expired = jwt.encode(
        {"sub": "user-123", "type": "access", "iat": now - 120, "exp": now - 60},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(TokenError):
        decode_token(expired, expected_type=TokenType.ACCESS)


def test_decode_rejects_bad_signature() -> None:
    token = create_access_token("user-123")
    with pytest.raises(TokenError):
        decode_token(token + "tampered", expected_type=TokenType.ACCESS)


def test_access_and_refresh_ttls_match_spec() -> None:
    """Wave 2B spec: 15 minute access tokens, 7 day refresh tokens."""
    settings = get_settings()
    assert settings.jwt_access_ttl_seconds == 15 * 60
    assert settings.jwt_refresh_ttl_seconds == 7 * 24 * 60 * 60
