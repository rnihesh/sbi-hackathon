"""Memory transparency: let a customer see and forget what Sarathi remembers.

The privacy differentiator - a plain-language "what we know about you" surface
with per-item and wholesale forget. All endpoints are auth-required and scoped
to the caller's own customer row (ownership enforced in the WHERE clause), so
one customer can never read or delete another's memories.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.memory import profile_facts
from app.core.db import get_db
from app.core.security import get_current_user
from app.models.identity import User
from app.models.memory import AgentMemory
from app.schemas.memory import MemoryDeleteAllResponse, MemoryItemOut, MemoryResponse

from .customers import _customer_for_user_or_404

router = APIRouter(prefix="/me/memory", tags=["memory"])

_MEMORY_LIMIT = 100


@router.get("", response_model=MemoryResponse)
async def get_memory(
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> MemoryResponse:
    """The 100 most recent memories (newest first) + the structured profile facts."""
    customer = await _customer_for_user_or_404(db, user)
    rows = (
        await db.scalars(
            select(AgentMemory)
            .where(AgentMemory.customer_id == customer.id)
            .order_by(AgentMemory.created_at.desc(), AgentMemory.id.desc())
            .limit(_MEMORY_LIMIT)
        )
    ).all()
    facts = await profile_facts(db, customer.id)
    return MemoryResponse(
        memories=[MemoryItemOut.model_validate(r) for r in rows],
        profile_facts=facts,
    )


@router.delete("/{memory_id}", status_code=204)
async def forget_memory(
    memory_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Forget a single memory. 404 if it does not exist or is not the caller's."""
    customer = await _customer_for_user_or_404(db, user)
    row = await db.scalar(
        select(AgentMemory).where(
            AgentMemory.id == memory_id,
            AgentMemory.customer_id == customer.id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    await db.delete(row)
    await db.flush()
    return Response(status_code=204)


@router.delete("", response_model=MemoryDeleteAllResponse)
async def forget_all_memory(
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> MemoryDeleteAllResponse:
    """Forget every memory for the caller's customer. Scoped by customer_id."""
    customer = await _customer_for_user_or_404(db, user)
    result = cast(
        "CursorResult[Any]",
        await db.execute(delete(AgentMemory).where(AgentMemory.customer_id == customer.id)),
    )
    return MemoryDeleteAllResponse(deleted=max(result.rowcount, 0))
