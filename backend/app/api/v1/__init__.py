"""API v1 router assembly."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    auth,
    chat,
    console,
    customers,
    demo,
    goals,
    insights,
    memory,
    notifications,
    nudges,
    products,
    standing,
)

api_router = APIRouter(prefix="/v1")
api_router.include_router(auth.router)
api_router.include_router(auth.me_router)
api_router.include_router(chat.router)
api_router.include_router(customers.router)
api_router.include_router(demo.router)
api_router.include_router(goals.router)
api_router.include_router(standing.router)
api_router.include_router(insights.router)
api_router.include_router(nudges.router)
api_router.include_router(notifications.router)
api_router.include_router(products.router)
api_router.include_router(memory.router)
api_router.include_router(console.router)


@api_router.get("/ping", tags=["meta"])
async def ping() -> dict[str, str]:
    """Liveness ping for the v1 API surface."""
    return {"status": "ok", "api": "v1"}
