"""API v1 router skeleton.

Wave-specific routers (auth, chat, customers, console, ...) will be included here
in later waves. For now this exposes an empty ``api_router`` to mount in main.py.
"""

from __future__ import annotations

from fastapi import APIRouter

api_router = APIRouter(prefix="/v1")


@api_router.get("/ping", tags=["meta"])
async def ping() -> dict[str, str]:
    """Liveness ping for the v1 API surface."""
    return {"status": "ok", "api": "v1"}
