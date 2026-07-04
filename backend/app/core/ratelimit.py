"""Redis-backed request rate limiting.

A small, dependency-free (no new packages) fixed-window limiter built on Redis
``INCR``+``EXPIRE``. :func:`rate_limit` is a factory that returns a FastAPI
dependency; attach it to a route via ``dependencies=[Depends(rate_limit(...))]``.

Design notes
------------
- **Fixed window, not sliding.** A key ``ratelimit:{name}:{identity}`` counts
  requests inside a ``window_seconds`` bucket; the first request in a window sets
  the TTL, so the whole window expires atomically once it elapses. This is the
  cheapest correct option (one ``INCR`` on the hot path) and is what the brief
  asked for. A fixed window can admit up to ``2*limit`` requests across a window
  boundary in the worst case - acceptable for abuse control here, where the goal
  is to stop runaways (LLM spend) rather than meter to the exact request.
- **Key strategy.** ``by_user`` keys on the authenticated user id decoded straight
  from the access-cookie JWT (no DB hit), falling back to the client IP for
  anonymous callers - so the expensive chat endpoint is limited per signed-in user
  yet still bounded for prospects. ``by_ip`` always keys on the client IP (used for
  cross-email abuse on OTP send).
- **Client IP** honours ``X-Forwarded-For``'s first hop only when the deployment
  is configured to trust it (prod behind nginx, or an explicit dev flag); in plain
  dev the socket peer is used so a caller cannot spoof the header to dodge limits.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal

from fastapi import Request

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.core.security import ACCESS_COOKIE, TokenError, TokenType, decode_token

logger = get_logger(__name__)

KeyStrategy = Literal["by_user", "by_ip"]


class RateLimitExceeded(Exception):  # noqa: N818 - conventional name for a 429 signal
    """Raised by a :func:`rate_limit` dependency when a caller is over its budget.

    Carries the seconds until the window resets so the exception handler can emit
    both a ``retry_after_seconds`` body field and a ``Retry-After`` header.
    """

    def __init__(self, *, name: str, retry_after_seconds: int) -> None:
        self.name = name
        self.retry_after_seconds = max(1, retry_after_seconds)
        super().__init__(f"rate limit '{name}' exceeded")


def client_ip(request: Request) -> str:
    """Best-effort client IP, honouring a trusted ``X-Forwarded-For`` first hop."""
    if get_settings().trust_client_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            first = forwarded.split(",", 1)[0].strip()
            if first:
                return first
    return request.client.host if request.client else "unknown"


def _identity(request: Request, key: KeyStrategy) -> str:
    """Resolve the rate-limit bucket identity for ``request`` under ``key``."""
    if key == "by_user":
        token = request.cookies.get(ACCESS_COOKIE)
        if token:
            try:
                payload = decode_token(token, expected_type=TokenType.ACCESS)
            except TokenError:
                payload = {}
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
    return f"ip:{client_ip(request)}"


def rate_limit(
    name: str,
    limit: int,
    window_seconds: int,
    key: KeyStrategy = "by_user",
) -> Callable[[Request], Awaitable[None]]:
    """Build a FastAPI dependency enforcing ``limit`` requests per ``window_seconds``.

    ``name`` namespaces the Redis counter (so two routes with the same limit do not
    share a bucket). ``key`` selects the bucket identity (see module docstring).
    Raises :class:`RateLimitExceeded` when the caller is over budget; otherwise
    returns ``None`` and lets the request proceed.
    """

    async def dependency(request: Request) -> None:
        identity = _identity(request, key)
        redis = get_redis()
        redis_key = f"ratelimit:{name}:{identity}"

        count = await redis.incr(redis_key)
        if count == 1:
            # First hit of a fresh window: stamp the TTL that expires the whole bucket.
            await redis.expire(redis_key, window_seconds)
            ttl = window_seconds
        else:
            ttl = await redis.ttl(redis_key)
            if ttl < 0:
                # Key exists without a TTL (expire lost to a crash between INCR and
                # EXPIRE): re-arm it so the bucket can never get stuck counting forever.
                await redis.expire(redis_key, window_seconds)
                ttl = window_seconds

        if count > limit:
            logger.warning(
                "rate_limited", limit_name=name, identity=identity, count=count, limit=limit
            )
            raise RateLimitExceeded(name=name, retry_after_seconds=ttl)

    return dependency
