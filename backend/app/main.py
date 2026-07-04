"""FastAPI application factory, lifespan, middleware, and health checks."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from sqlalchemy import text

from app.agents.checkpointer import close_checkpointer
from app.agents.entrypoints import init_agents
from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.db import dispose_engine, get_engine
from app.core.errors import (
    REQUEST_ID_HEADER,
    bind_request_id,
    error_envelope,
    install_error_handlers,
)
from app.core.logging import get_logger, setup_logging
from app.core.redis import close_redis, get_redis

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialise shared resources on startup; dispose them on shutdown."""
    setup_logging()
    settings = get_settings()
    logger.info("startup", app_env=settings.app_env)

    # Warm the engine and redis client (created lazily; construct now).
    get_engine()
    get_redis()
    await init_agents()

    try:
        yield
    finally:
        await close_checkpointer()
        await dispose_engine()
        await close_redis()
        logger.info("shutdown")


def _oversize_response(request: Request, request_id: str) -> ORJSONResponse | None:
    """Return a 413 envelope if the request's ``Content-Length`` exceeds the cap."""
    raw = request.headers.get("content-length")
    if not raw:
        return None
    try:
        length = int(raw)
    except ValueError:
        return None
    limit = get_settings().max_request_bytes
    if length <= limit:
        return None
    logger.warning("request_body_too_large", content_length=length, limit=limit)
    return ORJSONResponse(
        status_code=413,
        content=error_envelope(
            code="payload_too_large",
            message=f"Request body exceeds the {limit}-byte limit.",
            request_id=request_id,
        ),
        headers={REQUEST_ID_HEADER: request_id},
    )


async def _check_db() -> bool:
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("healthz_db_failed", error=str(exc))
        return False


async def _check_redis() -> bool:
    try:
        redis = get_redis()
        return bool(await redis.ping())
    except Exception as exc:
        logger.warning("healthz_redis_failed", error=str(exc))
        return False


def create_app() -> FastAPI:
    """Build and configure the Sarathi FastAPI application."""
    setup_logging()
    settings = get_settings()

    app = FastAPI(
        title="Sarathi API",
        version="0.1.0",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = bind_request_id(request)
        try:
            # Global body-size cap: reject oversized payloads before they reach a
            # route (and before any DB/LLM work). Header-based - our clients always
            # send Content-Length - returning the same error envelope as everything
            # else so the frontend handles it uniformly.
            oversized = _oversize_response(request, request_id)
            if oversized is not None:
                return oversized

            started = time.perf_counter()
            try:
                response = await call_next(request)
            except Exception:
                # An unhandled error still propagates to the 500 handler (which owns
                # the traceback log + error-ring tail); we only note timing here.
                duration_ms = round((time.perf_counter() - started) * 1000, 2)
                logger.warning(
                    "request_errored",
                    method=request.method,
                    path=request.url.path,
                    duration_ms=duration_ms,
                )
                raise
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=duration_ms,
            )
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            structlog.contextvars.clear_contextvars()

    install_error_handlers(app)

    @app.get("/healthz", tags=["meta"])
    async def healthz() -> ORJSONResponse:
        db_ok = await _check_db()
        redis_ok = await _check_redis()
        ok = db_ok and redis_ok
        return ORJSONResponse(
            status_code=200 if ok else 503,
            content={
                "status": "ok" if ok else "degraded",
                "db": db_ok,
                "redis": redis_ok,
            },
        )

    app.include_router(api_router, prefix="/api")

    return app


app = create_app()
