"""Structured error envelope, request-id propagation, and exception handlers.

Every error the API emits - a raised :class:`HTTPException`, a request-validation
failure (422), a rate-limit rejection (429), or an unhandled crash (500) - is
serialized through one consistent envelope::

    {
      "error": {"code": "not_found", "message": "...", "request_id": "abc123..."},
      "detail": "..."            # top-level alias: the frontend's ApiError reads this
    }

The ``detail`` alias mirrors what FastAPI returned before this module existed, so
the existing frontend contract keeps working unchanged. Validation errors keep
``detail`` as the familiar list-of-errors; everything else keeps it as the human
message string.

``request_id`` is generated (or accepted from an inbound ``X-Request-ID``) by
:func:`get_request_id`, bound to structlog for every log line, and echoed back in
both the response body and the ``X-Request-ID`` header so a user-reported error can
be traced to its exact log context.

Unhandled 500s additionally push a compact record onto a capped Redis ring
(``LPUSH`` + ``LTRIM``) that ``GET /console/errors`` reads, giving staff a live tail
of recent failures without any external error-tracking SaaS.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any

import orjson
import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse

from app.core.logging import get_logger
from app.core.ratelimit import RateLimitExceeded
from app.core.redis import get_redis

logger = get_logger(__name__)

REQUEST_ID_HEADER = "x-request-id"

# Capped Redis ring of recent unhandled errors (newest first), read by
# GET /console/errors. LPUSH prepends, LTRIM keeps only the newest N.
ERROR_RING_KEY = "console:errors"
ERROR_RING_MAX = 200


def get_request_id(request: Request) -> str:
    """Return this request's id, generating and caching one on first access.

    Prefers an inbound ``X-Request-ID`` (so a request id set by nginx / an upstream
    caller is preserved end to end), else a fresh 12-hex-char id. Cached on
    ``request.state`` so the middleware and any exception handler agree on one value.
    """
    existing = getattr(request.state, "request_id", None)
    if isinstance(existing, str) and existing:
        return existing
    inbound = request.headers.get(REQUEST_ID_HEADER)
    request_id = inbound if inbound else uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    return request_id


def _status_code_slug(status_code: int) -> str:
    """Map an HTTP status to a stable machine slug (e.g. 404 -> ``not_found``)."""
    try:
        return HTTPStatus(status_code).name.lower()
    except ValueError:
        return "http_error"


def error_envelope(
    *,
    code: str,
    message: str,
    request_id: str,
    detail: Any = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical error body (see module docstring).

    ``detail`` defaults to ``message`` (the back-compat alias); pass an explicit
    value - e.g. the validation error list - to override it.
    """
    body: dict[str, Any] = {
        "error": {"code": code, "message": message, "request_id": request_id},
        "detail": message if detail is None else detail,
    }
    if extra:
        body.update(extra)
    return body


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    detail: Any = None,
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> ORJSONResponse:
    response_headers = {REQUEST_ID_HEADER: request_id}
    if headers:
        response_headers.update(headers)
    return ORJSONResponse(
        status_code=status_code,
        content=error_envelope(
            code=code, message=message, request_id=request_id, detail=detail, extra=extra
        ),
        headers=response_headers,
    )


async def _push_error_ring(entry: dict[str, Any]) -> None:
    """Best-effort append to the capped recent-errors ring (never raises)."""
    try:
        redis = get_redis()
        await redis.lpush(ERROR_RING_KEY, orjson.dumps(entry).decode())
        await redis.ltrim(ERROR_RING_KEY, 0, ERROR_RING_MAX - 1)
    except Exception:
        logger.warning("error_ring_push_failed", exc_info=True)


async def http_exception_handler(request: Request, exc: HTTPException) -> ORJSONResponse:
    request_id = get_request_id(request)
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return _error_response(
        status_code=exc.status_code,
        code=_status_code_slug(exc.status_code),
        message=message,
        request_id=request_id,
        detail=exc.detail,
        headers=dict(exc.headers) if exc.headers else None,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> ORJSONResponse:
    request_id = get_request_id(request)
    # Keep `detail` as FastAPI's familiar list-of-errors so any client already
    # introspecting validation failures keeps working; jsonable_encoder tames
    # non-serializable bits (ValueError contexts, bytes) the raw list can hold.
    return _error_response(
        status_code=422,
        code="validation_error",
        message="Request validation failed",
        request_id=request_id,
        detail=jsonable_encoder(exc.errors()),
    )


async def rate_limit_exception_handler(
    request: Request, exc: RateLimitExceeded
) -> ORJSONResponse:
    request_id = get_request_id(request)
    return _error_response(
        status_code=429,
        code="rate_limited",
        message="Too many requests. Please slow down and try again shortly.",
        request_id=request_id,
        extra={"retry_after_seconds": exc.retry_after_seconds},
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> ORJSONResponse:
    """Last-resort 500 handler: log the full traceback, tail it to the error ring,
    and return a generic envelope that leaks no internals."""
    request_id = get_request_id(request)
    error_class = type(exc).__name__
    logger.error(
        "unhandled_exception",
        request_id=request_id,
        path=request.url.path,
        method=request.method,
        error_class=error_class,
        exc_info=exc,
    )
    await _push_error_ring(
        {
            "ts": datetime.now(UTC).isoformat(),
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
            "status": 500,
            "error_class": error_class,
        }
    )
    return _error_response(
        status_code=500,
        code="internal_error",
        message="An unexpected error occurred. Please try again.",
        request_id=request_id,
    )


def install_error_handlers(app: FastAPI) -> None:
    """Register the envelope handlers on ``app`` (call in the app factory)."""
    app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)


def bind_request_id(request: Request) -> str:
    """Resolve the request id and bind it to structlog contextvars for this request."""
    request_id = get_request_id(request)
    structlog.contextvars.bind_contextvars(request_id=request_id)
    return request_id
