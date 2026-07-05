"""Customer-facing ``/me/*`` API surface (auth required)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.core.security import get_current_user
from app.models.audit import AuditLog
from app.models.banking import Account
from app.models.catalog import Holding
from app.models.crm import Lead
from app.models.customer import Customer
from app.models.engagement import LifeEvent, Nudge, Proposal
from app.models.enums import NudgeStatus
from app.models.goal import SavingsGoal
from app.models.identity import User
from app.schemas.auth import CustomerOut
from app.schemas.customer import (
    AccountOut,
    ActivityItemOut,
    ActivityResponse,
    DashboardResponse,
    HoldingOut,
    PreferencesUpdateRequest,
    ProductOut,
    TransactionOut,
)
from app.services import ledger

router = APIRouter(prefix="/me", tags=["customers"])

_RECENT_TRANSACTIONS_LIMIT = 20
_ACTIVITY_LIMIT_DEFAULT = 30
_ACTIVITY_LIMIT_MAX = 100


async def _customer_for_user_or_404(db: AsyncSession, user: User) -> Customer:
    result = await db.execute(select(Customer).where(Customer.user_id == user.id))
    customer = result.scalar_one_or_none()
    if customer is None:
        raise HTTPException(status_code=404, detail="No customer profile for this account yet")
    return customer


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> DashboardResponse:
    customer = await _customer_for_user_or_404(db, user)

    accounts = await ledger.list_accounts(db, customer.id)

    # Spans every account belonging to the customer (joined on Account.customer_id).
    txns = await ledger.get_latest_transactions(db, customer.id, limit=_RECENT_TRANSACTIONS_LIMIT)

    holdings_result = await db.execute(
        select(Holding)
        .where(Holding.customer_id == customer.id)
        .options(selectinload(Holding.product))
    )
    holdings = holdings_result.scalars().all()

    unseen_count = await db.scalar(
        select(func.count())
        .select_from(Nudge)
        .where(Nudge.customer_id == customer.id, Nudge.status == NudgeStatus.SENT)
    )

    return DashboardResponse(
        customer=CustomerOut.model_validate(customer),
        accounts=[AccountOut.model_validate(a) for a in accounts],
        recent_transactions=[TransactionOut.model_validate(t) for t in txns],
        holdings=[
            HoldingOut(id=h.id, product=ProductOut.model_validate(h.product), status=h.status.value)
            for h in holdings
        ],
        unseen_nudges=int(unseen_count or 0),
    )


@router.patch("/preferences", response_model=CustomerOut, summary="Update profile and preferences")
async def update_preferences(
    payload: PreferencesUpdateRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> CustomerOut:
    """Partially update the customer's profile fields and chat preferences.

    Only fields present in the request body are touched - a client can PATCH
    just ``{"city": "Pune"}`` without clobbering name/phone/language. ``phone``
    and ``city`` accept explicit ``null`` to clear; so does
    ``preferred_language`` (returns Sarathi to "auto": agents reply in
    whatever language the customer writes in). ``full_name`` cannot be
    cleared - the column is not nullable.
    """
    customer = await _customer_for_user_or_404(db, user)
    fields_set = payload.model_fields_set
    if "preferred_language" in fields_set:
        customer.preferred_language = payload.preferred_language
    if "full_name" in fields_set and payload.full_name is not None:
        customer.full_name = payload.full_name
    if "phone" in fields_set:
        customer.phone = payload.phone
    if "city" in fields_set:
        customer.city = payload.city
    await db.flush()
    return CustomerOut.model_validate(customer)


# ===========================================================================
# Account activity (privacy surface - GET /me/activity)
# ===========================================================================
#
# Sourced from the tamper-evident `audit_log` table (see `app.agents.guardrails.
# AuditTrail`), not the `notifications` inbox - this is a fuller historical record of
# "things that happened on your account" than just the actionable alerts that also
# get a `Notification` row.
#
# Only a hand-picked allowlist of (action, entity) pairs is surfaced below, and only
# where that entity is *reliably and directly* linked to the caller's own
# `customer_id` via an explicit join + WHERE - never a fuzzy match on name/email.
# Everything else current agent/console code writes to the audit log is deliberately
# excluded:
#
# - `intent.classified` / `agent.response` (entity=conversation): internal supervisor
#   telemetry that fires on every chat turn - not a discrete, customer-meaningful
#   "activity", and would flood this log.
# - `churn.scored` (entity=customer, entity_id IS the customer id - attribution here
#   is trivially reliable): excluded on content grounds, not attribution - an internal
#   risk-model score is not something to surface to the customer it scores.
# - `note.created` / `note.deleted` (entity=staff_note): private internal staff
#   annotations about the customer. Never customer-facing, regardless of how
#   reliably they attribute.
# - `proposal.created` / `proposal.rejected` (entity=proposal): internal HITL working
#   states describing something that has NOT happened (or, once rejected, never will)
#   to the customer. Only `proposal.executed` reflects a real, delivered action -
#   showing the others would leak internal approval-queue mechanics.


@dataclass(slots=True)
class _ActivityRow:
    ts: datetime
    action: str
    summary: str


async def _lead_activity(
    db: AsyncSession, customer_id: uuid.UUID, limit: int
) -> list[_ActivityRow]:
    stmt = (
        select(AuditLog.ts, AuditLog.action, AuditLog.payload)
        .join(Lead, sa.cast(Lead.id, sa.String) == AuditLog.entity_id)
        .where(
            AuditLog.entity == "lead",
            AuditLog.action.in_(("lead.created", "kyc.verified")),
            Lead.customer_id == customer_id,
        )
        .order_by(AuditLog.ts.desc())
        .limit(limit)
    )
    rows: list[_ActivityRow] = []
    for ts, action, payload in await db.execute(stmt):
        if action == "lead.created":
            rows.append(
                _ActivityRow(
                    ts=ts,
                    action="Application started",
                    summary="You started your Sarathi application.",
                )
            )
            continue
        status = str(payload.get("status", "")).replace("_", " ").strip()
        reason = payload.get("reason")
        if status == "verified":
            summary = "Your identity was verified."
        elif status:
            summary = f"Identity verification: {status}" + (f" ({reason})" if reason else "")
        else:
            summary = "Identity verification recorded."
        rows.append(_ActivityRow(ts=ts, action="Identity verification", summary=summary))
    return rows


async def _account_activity(
    db: AsyncSession, customer_id: uuid.UUID, limit: int
) -> list[_ActivityRow]:
    stmt = (
        select(AuditLog.ts, Account.type)
        .join(Account, sa.cast(Account.id, sa.String) == AuditLog.entity_id)
        .where(
            AuditLog.entity == "account",
            AuditLog.action == "account.opened",
            Account.customer_id == customer_id,
        )
        .order_by(AuditLog.ts.desc())
        .limit(limit)
    )
    rows: list[_ActivityRow] = []
    for ts, account_type in await db.execute(stmt):
        kind = account_type.value.replace("_", " ")
        rows.append(
            _ActivityRow(
                ts=ts, action="Account opened", summary=f"Your {kind} account was opened."
            )
        )
    return rows


async def _goal_activity(
    db: AsyncSession, customer_id: uuid.UUID, limit: int
) -> list[_ActivityRow]:
    stmt = (
        select(AuditLog.ts, SavingsGoal.name)
        .join(SavingsGoal, sa.cast(SavingsGoal.id, sa.String) == AuditLog.entity_id)
        .where(
            AuditLog.entity == "savings_goal",
            AuditLog.action == "goal.created",
            SavingsGoal.customer_id == customer_id,
        )
        .order_by(AuditLog.ts.desc())
        .limit(limit)
    )
    rows: list[_ActivityRow] = []
    for ts, name in await db.execute(stmt):
        rows.append(
            _ActivityRow(
                ts=ts,
                action="Savings goal created",
                summary=f'You created the savings goal "{name}".',
            )
        )
    return rows


async def _nudge_activity(
    db: AsyncSession, customer_id: uuid.UUID, limit: int
) -> list[_ActivityRow]:
    stmt = (
        select(AuditLog.ts, Nudge.title)
        .join(Nudge, sa.cast(Nudge.id, sa.String) == AuditLog.entity_id)
        .where(
            AuditLog.entity == "nudge",
            AuditLog.action == "nudge.created",
            Nudge.customer_id == customer_id,
        )
        .order_by(AuditLog.ts.desc())
        .limit(limit)
    )
    rows: list[_ActivityRow] = []
    for ts, title in await db.execute(stmt):
        rows.append(_ActivityRow(ts=ts, action="Suggestion for you", summary=title))
    return rows


# Plain-language phrasing per detected life-event type - deliberately vaguer than the
# raw `life_events.type`/`confidence` (which stay internal): the customer sees that
# something was noticed, not the agent mesh's classification of it.
_LIFE_EVENT_SUMMARY: dict[str, str] = {
    "job_change": "We noticed signs of a job change in your recent activity.",
    "new_child": "We noticed signs of a new addition to your family.",
    "home_intent": "We noticed you might be looking to buy a home.",
    "bonus": "We noticed a bonus or windfall in your recent activity.",
    "salary_hike": "We noticed a salary increase in your recent activity.",
    "marriage": "We noticed signs of an upcoming wedding.",
    "relocation": "We noticed signs that you might be relocating.",
    "travel": "We noticed travel activity on your account.",
}
_LIFE_EVENT_SUMMARY_FALLBACK = "We noticed a change worth a look in your recent activity."


async def _life_event_activity(
    db: AsyncSession, customer_id: uuid.UUID, limit: int
) -> list[_ActivityRow]:
    stmt = (
        select(AuditLog.ts, LifeEvent.type)
        .join(LifeEvent, sa.cast(LifeEvent.id, sa.String) == AuditLog.entity_id)
        .where(
            AuditLog.entity == "life_event",
            AuditLog.action == "life_event.recorded",
            LifeEvent.customer_id == customer_id,
        )
        .order_by(AuditLog.ts.desc())
        .limit(limit)
    )
    rows: list[_ActivityRow] = []
    for ts, etype in await db.execute(stmt):
        summary = _LIFE_EVENT_SUMMARY.get(etype.value, _LIFE_EVENT_SUMMARY_FALLBACK)
        rows.append(_ActivityRow(ts=ts, action="Activity noticed", summary=summary))
    return rows


async def _proposal_activity(
    db: AsyncSession, customer_id: uuid.UUID, limit: int
) -> list[_ActivityRow]:
    stmt = (
        select(AuditLog.ts, Proposal.title)
        .join(Proposal, sa.cast(Proposal.id, sa.String) == AuditLog.entity_id)
        .where(
            AuditLog.entity == "proposal",
            AuditLog.action == "proposal.executed",
            Proposal.customer_id == customer_id,
        )
        .order_by(AuditLog.ts.desc())
        .limit(limit)
    )
    rows: list[_ActivityRow] = []
    for ts, title in await db.execute(stmt):
        rows.append(_ActivityRow(ts=ts, action="Proposal executed for you", summary=title))
    return rows


@router.get("/activity", response_model=ActivityResponse, summary="Recent account activity")
async def get_activity(
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=_ACTIVITY_LIMIT_DEFAULT, ge=1, le=_ACTIVITY_LIMIT_MAX),
) -> ActivityResponse:
    """Reverse-chronological, human-readable log of things that happened on this
    customer's account - sourced from the tamper-evident audit log, filtered to a
    hand-picked allowlist of actions that are both reliably attributable to this
    customer and appropriate to show them (see the module comment above)."""
    customer = await _customer_for_user_or_404(db, user)

    # One session, so these run sequentially (AsyncSession is not safe for
    # concurrent use) - each is independently limited/ordered, then merged below.
    rows = (
        await _lead_activity(db, customer.id, limit)
        + await _account_activity(db, customer.id, limit)
        + await _goal_activity(db, customer.id, limit)
        + await _nudge_activity(db, customer.id, limit)
        + await _life_event_activity(db, customer.id, limit)
        + await _proposal_activity(db, customer.id, limit)
    )
    rows.sort(key=lambda r: r.ts, reverse=True)
    return ActivityResponse(
        activity=[
            ActivityItemOut(ts=r.ts, action=r.action, summary=r.summary) for r in rows[:limit]
        ]
    )
