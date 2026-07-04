"""Shared agent side-effects: creating Nudges (immediate, in-app) and Proposals
(human-in-the-loop for impactful actions like email/offers).

Kept separate from tool wiring so the executor (:mod:`app.agents.entrypoints`)
and multiple specialists reuse the exact same creation + audit logic.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.engagement import Nudge, Proposal
from app.models.enums import NudgeStatus, ProposalKind, ProposalStatus


async def create_nudge(
    session: AsyncSession,
    *,
    customer_id: uuid.UUID,
    title: str,
    body: str,
    cta: dict[str, Any] | None = None,
    proposal_id: uuid.UUID | None = None,
    status: NudgeStatus = NudgeStatus.SENT,
) -> Nudge:
    """Create an in-app nudge (low-risk, immediate)."""
    nudge = Nudge(
        customer_id=customer_id,
        proposal_id=proposal_id,
        title=title,
        body=body,
        cta=cta or {},
        status=status,
    )
    session.add(nudge)
    await session.flush()
    return nudge


async def create_proposal(
    session: AsyncSession,
    *,
    customer_id: uuid.UUID,
    agent: str,
    kind: ProposalKind | str,
    title: str,
    body: str,
    action: dict[str, Any],
) -> Proposal:
    """Create a pending proposal for HITL review (impactful action)."""
    proposal = Proposal(
        customer_id=customer_id,
        agent=agent,
        kind=kind if isinstance(kind, ProposalKind) else ProposalKind(kind),
        title=title,
        body=body,
        action=action,
        status=ProposalStatus.PENDING,
    )
    session.add(proposal)
    await session.flush()
    return proposal
