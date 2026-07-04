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


# Inner action["kind"] values that execute_proposal can dispatch. Anything else
# would strand the proposal as unapprovable, so tool layers normalize first.
EXECUTABLE_ACTION_KINDS = {"send_nudge", "nudge", "product_offer", "offer", "send_email", "email"}

_FALLBACK_ACTION_KINDS = {
    "email": "send_email",
    "product_offer": "product_offer",
    "offer": "product_offer",
    "nudge": "send_nudge",
}


def normalize_action_kind(inner: str | None, proposal_kind: str) -> str:
    """Coerce an LLM-supplied action kind to one the executor supports."""
    if inner in EXECUTABLE_ACTION_KINDS:
        return inner
    return _FALLBACK_ACTION_KINDS.get(proposal_kind, "send_nudge")


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
