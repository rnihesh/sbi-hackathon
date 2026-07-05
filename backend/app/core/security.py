"""Session security: JWT minting/verification, Redis-backed refresh rotation,
httpOnly cookie plumbing, and the ``get_current_user`` / ``get_optional_user``
FastAPI dependencies.

Sarathi authenticates via Google OAuth / passkeys / email OTP (Wave 2); this module
mints and verifies the resulting httpOnly JWT session cookies and tracks refresh-token
lifetime in Redis so sessions can be rotated and revoked server-side.

Session metadata (device/security surface)
--------------------------------------------
Each tracked session key (``session:{user_id}:{jti}``) used to store the bare marker
string ``"1"`` - just enough to answer "is this jti still active". It now stores a
small JSON object (:func:`create_session`) with a human-friendly device summary, a
privacy-truncated IP prefix, and creation/last-seen timestamps, so a signed-in user can
see and revoke their own active sessions (``GET``/``DELETE /auth/sessions``).

This is a compatible upgrade, not a migration: the key's TTL and revoke-by-delete
semantics are unchanged, only the *value* gained structure. A session created before
this change (or one whose value fails to parse as the expected JSON object) is treated
as a legacy/unknown session - :func:`list_sessions` reports it with ``device=None``
(the API layer renders that as "Unknown device") and no timestamps, rather than
erroring. Once such a session next rotates its refresh token, :func:`rotate_session`
upgrades it to the new metadata shape (its ``created_at`` resets to that rotation
moment, since the true original login time was never recorded under the old format -
the one honest gap in an otherwise-compatible upgrade).

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

import ipaddress
import json
import secrets
import uuid
from dataclasses import dataclass
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

# Number of trailing jti characters exposed to the client as a session identifier.
# The full jti is never returned - see the module docstring on session metadata.
_JTI_SUFFIX_LEN = 6


def jti_suffix(jti: str) -> str:
    """The last few characters of a session jti - a display id only, never the jti."""
    return jti[-_JTI_SUFFIX_LEN:]


def summarize_user_agent(user_agent: str | None, *, fallback: str) -> str:
    """Small heuristic UA parse for a human-friendly summary (e.g. "Chrome on Mac").

    ``fallback`` is returned verbatim for a missing/empty ``user_agent`` - callers pick
    a fallback that fits their context (e.g. "Passkey" when labelling a credential,
    "Unknown device" when summarising a session).
    """
    if not user_agent:
        return fallback

    if "iPhone" in user_agent:
        device = "iPhone"
    elif "iPad" in user_agent:
        device = "iPad"
    elif "Android" in user_agent:
        device = "Android"
    elif "Macintosh" in user_agent or "Mac OS" in user_agent:
        device = "Mac"
    elif "Windows" in user_agent:
        device = "Windows"
    elif "Linux" in user_agent:
        device = "Linux"
    else:
        device = "device"

    if "Edg/" in user_agent:
        browser = "Edge"
    elif "CriOS" in user_agent or ("Chrome/" in user_agent and "Chromium" not in user_agent):
        browser = "Chrome"
    elif "Firefox/" in user_agent:
        browser = "Firefox"
    elif "Safari/" in user_agent and "Chrome/" not in user_agent:
        browser = "Safari"
    else:
        return fallback

    return f"{browser} on {device}"


def _truncate_ip_prefix(ip: str | None) -> str | None:
    """Truncate ``ip`` to a coarse, non-identifying network prefix (``/24`` for IPv4,
    ``/48`` for IPv6), or ``None`` if ``ip`` is missing/unparseable (e.g. "unknown",
    the ``client_ip`` fallback for a socket with no peer)."""
    if not ip:
        return None
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    prefixlen = 24 if addr.version == 4 else 48
    network = ipaddress.ip_network(f"{addr}/{prefixlen}", strict=False)
    return f"{network.network_address}/{prefixlen}"


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
# Redis-backed refresh session tracking (issue / rotate / revoke / list)
# --------------------------------------------------------------------------------------


def _session_key(user_id: str, jti: str) -> str:
    return f"{_SESSION_KEY_PREFIX}:{user_id}:{jti}"


@dataclass(slots=True, frozen=True)
class SessionInfo:
    """One active session as reported by :func:`list_sessions`.

    ``device``/``created_at``/``last_seen_at`` are ``None`` for a legacy session (one
    created before the metadata upgrade, or whose value otherwise failed to parse) -
    see the module docstring. ``ip_prefix`` is collected for potential future display
    but the current ``/auth/sessions`` API intentionally does not expose it (device +
    relative time is plenty to recognise "is this me"; a network prefix is noise).
    """

    jti: str
    device: str | None
    ip_prefix: str | None
    created_at: str | None
    last_seen_at: str | None


def _decode_session_metadata(raw: str | bytes | None) -> dict[str, Any] | None:
    """Parse a session Redis value into its metadata dict.

    Returns ``None`` for a missing value, the legacy bare marker (``"1"``), or anything
    else that fails to decode as a JSON object - all treated identically as "no
    metadata on file for this session" by callers. ``bytes`` is accepted defensively
    (the process-wide client is configured with ``decode_responses=True`` so this
    always sees ``str`` in practice, but the client's type stubs are generic).
    """
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


async def create_session(
    user_id: str,
    *,
    user_agent: str | None = None,
    ip: str | None = None,
    created_at: str | None = None,
) -> tuple[str, str]:
    """Issue a fresh access+refresh token pair for ``user_id``.

    The refresh token's ``jti`` is recorded in Redis with a TTL matching the refresh
    token's own lifetime; only jtis present in Redis are accepted on rotation/use. The
    Redis value carries device/IP/timing metadata for the sessions security surface -
    ``user_agent``/``ip`` are the *new* request's (so "last seen" reflects the device
    presenting this token pair); ``created_at`` lets :func:`rotate_session` carry a
    session's original creation time forward across rotations (omit it - the default,
    "now" - for a genuinely new login).
    """
    settings = get_settings()
    jti = secrets.token_urlsafe(24)
    access_token = create_access_token(user_id)
    refresh_token = create_refresh_token(user_id, jti=jti)

    now_iso = datetime.now(tz=UTC).isoformat()
    metadata = {
        "device": summarize_user_agent(user_agent, fallback="Unknown device"),
        "ip_prefix": _truncate_ip_prefix(ip),
        "created_at": created_at or now_iso,
        "last_seen_at": now_iso,
    }

    redis = get_redis()
    await redis.set(
        _session_key(user_id, jti), json.dumps(metadata), ex=settings.jwt_refresh_ttl_seconds
    )
    return access_token, refresh_token


async def rotate_session(
    refresh_token: str,
    *,
    user_agent: str | None = None,
    ip: str | None = None,
) -> tuple[str, str]:
    """Verify + consume ``refresh_token``, issuing a new access+refresh pair.

    The presented refresh token's ``jti`` is revoked (deleted) as part of rotation so a
    replayed/stolen refresh token can be used at most once. Raises :class:`SessionError`
    if the token is malformed, expired, or its ``jti`` is not an active session.

    The new session's metadata carries forward the old session's ``created_at`` (so
    "created" keeps reflecting the original login, not this rotation) while ``device``/
    ``ip_prefix``/``last_seen_at`` are refreshed from the caller-supplied ``user_agent``/
    ``ip`` of *this* rotation request.
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
    # Read the old metadata (best-effort - only used to carry `created_at` forward)
    # before deleting; the delete result is still the authoritative revoke check.
    previous_raw = await redis.get(key)
    deleted = await redis.delete(key)
    if not deleted:
        raise SessionError("refresh session is not active (expired or revoked)")

    previous = _decode_session_metadata(previous_raw)
    carried_created_at = previous.get("created_at") if previous else None

    return await create_session(
        user_id, user_agent=user_agent, ip=ip, created_at=carried_created_at
    )


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


async def list_sessions(user_id: str) -> list[SessionInfo]:
    """All of ``user_id``'s currently-active (unexpired, unrevoked) sessions.

    Order is unspecified here - callers (the ``/auth/sessions`` route) sort for
    display. Uses ``SCAN`` (not ``KEYS``) so this never blocks Redis even if a user
    somehow accumulates many sessions.
    """
    redis = get_redis()
    pattern = _session_key(user_id, "*")
    sessions: list[SessionInfo] = []
    async for key in redis.scan_iter(match=pattern):
        jti = key.split(":", 2)[2]
        raw = await redis.get(key)
        if raw is None:
            continue  # expired between the SCAN and this GET
        metadata = _decode_session_metadata(raw)
        sessions.append(
            SessionInfo(
                jti=jti,
                device=metadata.get("device") if metadata else None,
                ip_prefix=metadata.get("ip_prefix") if metadata else None,
                created_at=metadata.get("created_at") if metadata else None,
                last_seen_at=metadata.get("last_seen_at") if metadata else None,
            )
        )
    return sessions


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


async def _user_from_present_access_cookie(access_token: str, db: AsyncSession) -> User:
    """Resolve a *present* access cookie to its :class:`User`, or raise ``401``.

    Any failure of a cookie that *is* present - malformed / expired / wrong-type
    token, an unparseable subject, or a token naming a user who no longer exists -
    is a broken (but real) session and raises ``401``. The caller decides what an
    *absent* cookie means; this function never sees one.
    """
    try:
        payload = decode_token(access_token, expected_type=TokenType.ACCESS)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session"
        ) from exc

    sub = payload.get("sub")
    user_id: uuid.UUID | None = None
    if sub:
        try:
            user_id = uuid.UUID(str(sub))
        except ValueError:
            user_id = None
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session subject"
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Session user not found"
        )
    return user


async def get_current_user(
    sarathi_access: Annotated[str | None, Cookie()] = None,
    db: AsyncSession = Depends(get_db),
) -> User:
    """FastAPI dependency: resolve the authenticated user from the access cookie.

    Raises ``401`` if the cookie is missing, invalid, expired, or names an unknown user.
    """
    if sarathi_access is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return await _user_from_present_access_cookie(sarathi_access, db)


async def get_optional_user(
    sarathi_access: Annotated[str | None, Cookie()] = None,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """FastAPI dependency for anon-friendly routes (e.g. chat onboarding).

    Three-state contract:

    - **no cookie** -> ``None``: a legitimate anonymous prospect.
    - **present but broken cookie** (malformed / expired / unknown user) -> ``401``:
      a real-but-dead session. Raising here rather than silently degrading to
      anonymous lets the frontend refresh interceptor rotate the access token and
      retry, instead of a signed-in user's chat quietly dropping to a prospect
      thread the moment their short-lived access token expires.
    - **valid cookie** -> the resolved :class:`User`.
    """
    if sarathi_access is None:
        return None
    return await _user_from_present_access_cookie(sarathi_access, db)
