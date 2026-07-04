"""Session security: JWT minting/verification, Redis-backed refresh rotation,
httpOnly cookie plumbing, and the ``get_current_user`` / ``get_optional_user``
FastAPI dependencies.

Sarathi authenticates via Google OAuth / passkeys / email OTP (Wave 2); this module
mints and verifies the resulting httpOnly JWT session cookies and tracks refresh-token
lifetime in Redis so sessions can be rotated and revoked server-side.

CSRF posture
------------
State-changing auth routes (``/auth/*``, ``/me`` mutations) are cookie-authenticated
with ``SameSite=Lax`` and CORS locked to a known, explicit, credentialed origin
(``settings.cors_origins`` - no wildcard). We deliberately do *not* add a double-submit
CSRF token on top of that:

- ``SameSite=Lax`` already withholds the cookie on cross-site *subresource* requests
  (fetch/XHR/form-POST from another origin), which is the only vector a CSRF token
  would defend against here. It is only sent on top-level, same-site navigation.
- The CORS policy only reflects `Access-Control-Allow-Origin` for the exact configured
  frontend origin with `Allow-Credentials: true`, so a malicious page on another origin
  cannot complete a credentialed cross-origin `fetch`/XHR (the browser blocks it at the
  preflight/response stage) and a bare `<form>` POST cannot read the response or attach
  custom headers/JSON bodies our routes require.
- Every mutating route here expects a JSON body (`Content-Type: application/json`),
  which is not a "simple request" and forces a CORS preflight - another cross-origin
  gate a plain HTML form cannot satisfy.

A double-submit token would add real value only if we accepted `SameSite=None` cookies,
served non-JSON form posts, or trusted a wildcard/multi-tenant CORS origin - none of
which apply. We *do* add the standard origin-bound nonces for the two ceremonies that
need them regardless of cookie posture: the OAuth ``state`` parameter (signed, itsdangerous)
and WebAuthn challenges (single-use, Redis-backed, short TTL).
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any

import jwt
from fastapi import Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.core.redis import get_redis
from app.models.identity import User

# httpOnly cookie names for the session pair.
ACCESS_COOKIE = "sarathi_access"
REFRESH_COOKIE = "sarathi_refresh"

# Redis key prefix for tracked (rotatable/revocable) refresh-token jtis.
_SESSION_KEY_PREFIX = "session"


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


class TokenError(Exception):
    """Raised when a token is missing, malformed, expired, or of the wrong type."""


class SessionError(Exception):
    """Raised when a refresh session is invalid, expired, or has been revoked."""


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


# --------------------------------------------------------------------------------------
# Redis-backed refresh session tracking (issue / rotate / revoke)
# --------------------------------------------------------------------------------------


def _session_key(user_id: str, jti: str) -> str:
    return f"{_SESSION_KEY_PREFIX}:{user_id}:{jti}"


async def create_session(user_id: str) -> tuple[str, str]:
    """Issue a fresh access+refresh token pair for ``user_id``.

    The refresh token's ``jti`` is recorded in Redis with a TTL matching the refresh
    token's own lifetime; only jtis present in Redis are accepted on rotation/use.
    """
    settings = get_settings()
    jti = secrets.token_urlsafe(24)
    access_token = create_access_token(user_id)
    refresh_token = create_refresh_token(user_id, jti=jti)

    redis = get_redis()
    await redis.set(_session_key(user_id, jti), "1", ex=settings.jwt_refresh_ttl_seconds)
    return access_token, refresh_token


async def rotate_session(refresh_token: str) -> tuple[str, str]:
    """Verify + consume ``refresh_token``, issuing a new access+refresh pair.

    The presented refresh token's ``jti`` is revoked (deleted) as part of rotation so a
    replayed/stolen refresh token can be used at most once. Raises :class:`SessionError`
    if the token is malformed, expired, or its ``jti`` is not an active session.
    """
    try:
        payload = decode_token(refresh_token, expected_type=TokenType.REFRESH)
    except TokenError as exc:
        raise SessionError(str(exc)) from exc

    user_id = payload.get("sub")
    jti = payload.get("jti")
    if not user_id or not jti:
        raise SessionError("refresh token missing sub/jti")

    redis = get_redis()
    key = _session_key(user_id, jti)
    deleted = await redis.delete(key)
    if not deleted:
        raise SessionError("refresh session is not active (expired or revoked)")

    return await create_session(user_id)


async def revoke_session(user_id: str, jti: str) -> None:
    """Revoke a single refresh session (idempotent)."""
    redis = get_redis()
    await redis.delete(_session_key(user_id, jti))


async def revoke_session_from_refresh_token(refresh_token: str) -> None:
    """Best-effort revoke of whatever session ``refresh_token`` names (used on logout).

    Silently no-ops on a malformed/expired token - logout must always succeed.
    """
    try:
        payload = decode_token(refresh_token, expected_type=TokenType.REFRESH)
    except TokenError:
        return
    user_id = payload.get("sub")
    jti = payload.get("jti")
    if user_id and jti:
        await revoke_session(str(user_id), str(jti))


# --------------------------------------------------------------------------------------
# Cookies
# --------------------------------------------------------------------------------------


def set_session_cookies(response: Response, *, access_token: str, refresh_token: str) -> None:
    """Attach the httpOnly session cookie pair to ``response``."""
    settings = get_settings()
    secure = not settings.is_dev
    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        max_age=settings.jwt_access_ttl_seconds,
        httponly=True,
        secure=secure,
        samesite="lax",
        domain=settings.cookie_domain,
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=settings.jwt_refresh_ttl_seconds,
        httponly=True,
        secure=secure,
        samesite="lax",
        domain=settings.cookie_domain,
        path="/",
    )


def clear_session_cookies(response: Response) -> None:
    """Remove both session cookies (logout / invalid-session recovery)."""
    settings = get_settings()
    response.delete_cookie(ACCESS_COOKIE, domain=settings.cookie_domain, path="/")
    response.delete_cookie(REFRESH_COOKIE, domain=settings.cookie_domain, path="/")


# --------------------------------------------------------------------------------------
# FastAPI dependencies
# --------------------------------------------------------------------------------------


async def _user_from_access_cookie(
    access_token: str | None, db: AsyncSession
) -> User | None:
    if not access_token:
        return None
    try:
        payload = decode_token(access_token, expected_type=TokenType.ACCESS)
    except TokenError:
        return None

    sub = payload.get("sub")
    if not sub:
        return None
    try:
        user_id = uuid.UUID(str(sub))
    except ValueError:
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_current_user(
    sarathi_access: Annotated[str | None, Cookie()] = None,
    db: AsyncSession = Depends(get_db),
) -> User:
    """FastAPI dependency: resolve the authenticated user from the access cookie.

    Raises ``401`` if the cookie is missing, invalid, expired, or names an unknown user.
    """
    user = await _user_from_access_cookie(sarathi_access, db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


async def get_optional_user(
    sarathi_access: Annotated[str | None, Cookie()] = None,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """FastAPI dependency: resolve the authenticated user if present, else ``None``."""
    return await _user_from_access_cookie(sarathi_access, db)
