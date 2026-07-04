"""JWT session helpers (password-less auth).

Sarathi authenticates via Google OAuth / passkeys / email OTP (Wave 2); this module
only mints and verifies the resulting httpOnly JWT session cookies.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import jwt

from app.core.config import get_settings

# httpOnly cookie names for the session pair.
ACCESS_COOKIE = "sarathi_access"
REFRESH_COOKIE = "sarathi_refresh"


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


class TokenError(Exception):
    """Raised when a token is missing, malformed, expired, or of the wrong type."""


def _create_token(subject: str, token_type: TokenType, ttl_seconds: int, **claims: Any) -> str:
    settings = get_settings()
    now = datetime.now(tz=UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type.value,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        **claims,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(subject: str, **claims: Any) -> str:
    """Mint a short-lived access token for ``subject`` (usually a user id)."""
    settings = get_settings()
    return _create_token(subject, TokenType.ACCESS, settings.jwt_access_ttl_seconds, **claims)


def create_refresh_token(subject: str, **claims: Any) -> str:
    """Mint a long-lived refresh token for ``subject``."""
    settings = get_settings()
    return _create_token(subject, TokenType.REFRESH, settings.jwt_refresh_ttl_seconds, **claims)


def decode_token(token: str, *, expected_type: TokenType | None = None) -> dict[str, Any]:
    """Decode and validate a JWT.

    Raises :class:`TokenError` if the signature/expiry is invalid or the token type
    does not match ``expected_type``.
    """
    settings = get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError as exc:  # pragma: no cover - thin wrapper
        raise TokenError(str(exc)) from exc

    if expected_type is not None and payload.get("type") != expected_type.value:
        raise TokenError(f"expected {expected_type.value} token, got {payload.get('type')!r}")
    return payload
