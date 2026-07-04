"""API v1 router assembly.

Wave-specific routers (chat, customers, console, ...) will be included here in later
waves; auth is wired up now.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth

api_router = APIRouter(prefix="/v1")
api_router.include_router(auth.router)
api_router.include_router(auth.me_router)


@api_router.get("/ping", tags=["meta"])
async def ping() -> dict[str, str]:
    """Liveness ping for the v1 API surface."""
    return {"status": "ok", "api": "v1"}
