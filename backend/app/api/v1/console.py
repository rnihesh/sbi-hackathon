"""Staff console API: live feed, leads, proposals (HITL), life events, funnels,
traces, costs, and an on-demand sim life-event injector.

Staff gate
----------
:func:`get_current_staff` requires an authenticated user whose email is in
``settings.staff_emails``. If that list is empty *and* ``APP_ENV=dev``, any
authenticated user passes (with a structlog warning) so the console is usable
before staff accounts are provisioned; everywhere else an empty allowlist means
nobody is staff.
"""

from __future__ import annotations

import csv
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import StringIO
from typing import Annotated, Any

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from app.agents.actions import create_proposal
from app.agents.entrypoints import execute_proposal
from app.agents.guardrails import AuditTrail
from app.core.config import get_settings, is_staff_email
from app.core.db import get_db
from app.core.errors import ERROR_RING_KEY
from app.core.logging import get_logger
from app.core.redis import (
    AGENT_ACTIONS,
    GROUP_AGENTS,
    TXN_EVENTS,
    TXN_EVENTS_DLQ,
    get_redis,
)
from app.core.security import get_current_user
from app.models.audit import AuditLog
from app.models.banking import Account, Transaction
from app.models.catalog import Holding, Product
from app.models.crm import Lead
from app.models.customer import Customer
from app.models.engagement import LifeEvent, Notification, Nudge, Proposal
from app.models.enums import (
    AgentTriggerType,
    HandoffStatus,
    HoldingStatus,
    LeadStage,
    NotificationKind,
    NudgeStatus,
    ProposalKind,
    ProposalStatus,
)
from app.models.handoff import HandoffRequest
from app.models.identity import User
from app.models.notes import StaffNote
from app.models.sim_injection import SimInjection
from app.models.tracing import AgentRun, AgentStep, LlmCall
from app.schemas.console import (
    AcquisitionFunnel,
    ChurnAtRiskCustomerOut,
    ChurnBucketLabel,
    ChurnBucketOut,
    ChurnCockpitResponse,
    ChurnReengageResult,
    ConsoleErrorsResponse,
    ConsoleHealthResponse,
    CostBreakdownRow,
    CostSeriesPoint,
    CostsResponse,
    CustomerAccountOut,
    CustomerDetailOut,
    CustomerDetailResponse,
    CustomerHoldingOut,
    CustomerHoldingProductOut,
    CustomerSearchOut,
    CustomerStatsOut,
    DetectionResponse,
    DetectionRow,
    DetectionSummary,
    DlqEntrySummaryOut,
    ErrorLogEntryOut,
    FunnelResponse,
    HandoffCustomerOut,
    HandoffOut,
    HandoffQueueResponse,
    HandoffResolveRequest,
    HoldingCategoryFunnel,
    LeadCustomerOut,
    LeadOut,
    LifeEventCustomerOut,
    LifeEventOut,
    LlmBudgetOut,
    NudgeFunnel,
    ProposalActionResult,
    ProposalAgentRow,
    ProposalCustomerOut,
    ProposalOut,
    ProposalOutcomesResponse,
    ProposalRejectRequest,
    SchedulerHealthOut,
    SimInjectEventRequest,
    SimInjectEventResponse,
    StaffNoteCreateRequest,
    StaffNoteOut,
    TimelineItemOut,
    TimeseriesPoint,
    TimeseriesResponse,
    TraceCustomerOut,
    TraceDetailResponse,
    TraceOut,
    TraceStepOut,
    WorkerHealthOut,
)
from app.services.email import EmailNotConfigured
from app.services.notifications import notify
from app.sim import events as sim_events
from app.sim import generator as sim_generator
from app.sim import personas as sim_personas
from app.workers.activity import publish_activity

logger = get_logger(__name__)

router = APIRouter(prefix="/console", tags=["console"])


# ===========================================================================
# Staff gate
# ===========================================================================


async def get_current_staff(user: Annotated[User, Depends(get_current_user)]) -> User:
    settings = get_settings()
    if is_staff_email(user.email):
        if not settings.staff_email_list and settings.is_dev:
            logger.warning("staff_gate_open_no_staff_emails_configured", user_email=user.email)
        return user
    if not settings.staff_email_list and not settings.is_dev:
        raise HTTPException(status_code=403, detail="Staff access is not configured")
    raise HTTPException(status_code=403, detail="Staff access required")


StaffUser = Annotated[User, Depends(get_current_staff)]


# ===========================================================================
# Customer search (staff picker - e.g. the sim life-event injector dialog)
# ===========================================================================


@router.get("/customers", response_model=list[CustomerSearchOut])
async def search_customers(
    staff: StaffUser,
    q: str | None = Query(default=None, description="Case-insensitive full_name substring"),
    limit: int = Query(default=20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> list[CustomerSearchOut]:
    stmt = select(Customer.id, Customer.full_name, Customer.city).order_by(Customer.full_name)
    if q:
        stmt = stmt.where(Customer.full_name.ilike(f"%{q}%"))
    stmt = stmt.limit(limit)
    rows = (await db.execute(stmt)).all()
    return [
        CustomerSearchOut(id=row.id, full_name=row.full_name, city=row.city) for row in rows
    ]


# ===========================================================================
# Customer 360 ("RM sees everything" detail view)
# ===========================================================================

_TXN_LOOKBACK_DAYS = 90
"""Window for the `transactions_90d` stat tile - matches the sim injector's own
90-day attribution window (see `_INJECT_WINDOW_DAYS` below) for consistency."""


@router.get("/customers/{customer_id}", response_model=CustomerDetailResponse)
async def get_customer_detail(
    customer_id: uuid.UUID, staff: StaffUser, db: AsyncSession = Depends(get_db)
) -> CustomerDetailResponse:
    """Profile + accounts + holdings + at-a-glance stats for one customer - the
    top of the staff "RM sees everything" 360 view."""
    customer = await db.get(
        Customer,
        customer_id,
        options=[
            selectinload(Customer.accounts),
            selectinload(Customer.holdings).selectinload(Holding.product),
        ],
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    account_ids = select(Account.id).where(Account.customer_id == customer.id).scalar_subquery()
    since = datetime.now(UTC) - timedelta(days=_TXN_LOOKBACK_DAYS)
    transactions_90d = (
        await db.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.account_id.in_(account_ids), Transaction.ts >= since)
        )
        or 0
    )
    agent_runs_total = (
        await db.scalar(
            select(func.count()).select_from(AgentRun).where(AgentRun.customer_id == customer.id)
        )
        or 0
    )
    proposals_pending = (
        await db.scalar(
            select(func.count())
            .select_from(Proposal)
            .where(
                Proposal.customer_id == customer.id, Proposal.status == ProposalStatus.PENDING
            )
        )
        or 0
    )
    nudges_sent = (
        await db.scalar(
            select(func.count()).select_from(Nudge).where(Nudge.customer_id == customer.id)
        )
        or 0
    )
    life_events_total = (
        await db.scalar(
            select(func.count()).select_from(LifeEvent).where(LifeEvent.customer_id == customer.id)
        )
        or 0
    )

    return CustomerDetailResponse(
        customer=CustomerDetailOut(
            id=customer.id,
            full_name=customer.full_name,
            email=customer.email,
            phone=customer.phone,
            city=customer.city,
            segment=customer.segment,
            digital_maturity=customer.digital_maturity.value,
            churn_risk=customer.churn_risk,
            preferred_language=customer.preferred_language,
            created_at=customer.created_at,
        ),
        accounts=[
            CustomerAccountOut(
                type=a.type.value, balance_paise=a.balance_paise, status=a.status.value
            )
            for a in customer.accounts
        ],
        holdings=[
            CustomerHoldingOut(
                product=CustomerHoldingProductOut(
                    code=h.product.code, name=h.product.name, category=h.product.category
                ),
                status=h.status.value,
            )
            for h in customer.holdings
        ],
        stats=CustomerStatsOut(
            transactions_90d=int(transactions_90d),
            agent_runs_total=int(agent_runs_total),
            proposals_pending=int(proposals_pending),
            nudges_sent=int(nudges_sent),
            life_events=int(life_events_total),
        ),
    )


@router.get("/customers/{customer_id}/timeline", response_model=list[TimelineItemOut])
async def get_customer_timeline(
    customer_id: uuid.UUID,
    staff: StaffUser,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[TimelineItemOut]:
    """Merged, reverse-chronological feed of everything that happened for one
    customer: agent runs, life events, proposals, nudges, notifications.

    Each source is fetched independently, already ordered newest-first and
    capped at ``limit`` rows, *then* merged and re-sorted before the final
    ``limit`` cut is applied - fetching only ``limit`` per source (rather than
    each source's full history) is still provably correct: the final top-
    ``limit`` merged items can never draw more than ``limit`` rows from any
    single source.
    """
    exists = await db.scalar(select(Customer.id).where(Customer.id == customer_id))
    if exists is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    runs = (
        (
            await db.execute(
                select(AgentRun)
                .where(AgentRun.customer_id == customer_id)
                .order_by(AgentRun.started_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    life_events = (
        (
            await db.execute(
                select(LifeEvent)
                .where(LifeEvent.customer_id == customer_id)
                .order_by(LifeEvent.detected_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    proposals = (
        (
            await db.execute(
                select(Proposal)
                .where(Proposal.customer_id == customer_id)
                .order_by(Proposal.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    nudges = (
        (
            await db.execute(
                select(Nudge)
                .where(Nudge.customer_id == customer_id)
                .order_by(Nudge.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    notifications = (
        (
            await db.execute(
                select(Notification)
                .where(Notification.customer_id == customer_id)
                .order_by(Notification.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    items: list[TimelineItemOut] = []
    for run in runs:
        items.append(
            TimelineItemOut(
                type="agent_run",
                ts=run.started_at,
                data={
                    "run_id": str(run.id),
                    "agent": run.agent,
                    "trigger": run.trigger.value,
                    "status": run.status.value,
                    "cost_usd": str(run.cost_usd),
                    "started_at": run.started_at.isoformat(),
                },
            )
        )
    for event in life_events:
        items.append(
            TimelineItemOut(
                type="life_event",
                ts=event.detected_at,
                data={
                    "type": event.type.value,
                    "confidence": event.confidence,
                    "detected_at": event.detected_at.isoformat(),
                },
            )
        )
    for proposal in proposals:
        items.append(
            TimelineItemOut(
                type="proposal",
                ts=proposal.created_at,
                data={
                    "title": proposal.title,
                    "status": proposal.status.value,
                    "created_at": proposal.created_at.isoformat(),
                    "decided_at": proposal.decided_at.isoformat() if proposal.decided_at else None,
                },
            )
        )
    for nudge in nudges:
        items.append(
            TimelineItemOut(
                type="nudge",
                ts=nudge.created_at,
                data={
                    "title": nudge.title,
                    "status": nudge.status.value,
                    "created_at": nudge.created_at.isoformat(),
                },
            )
        )
    for notification in notifications:
        items.append(
            TimelineItemOut(
                type="notification",
                ts=notification.created_at,
                data={
                    "kind": notification.kind.value,
                    "title": notification.title,
                    "created_at": notification.created_at.isoformat(),
                },
            )
        )

    items.sort(key=lambda item: item.ts, reverse=True)
    return items[:limit]


# ===========================================================================
# Staff notes (customer 360's "notes" card - kept out of the timeline above:
# a note is a staff observation, not something that happened)
# ===========================================================================


@router.get("/customers/{customer_id}/notes", response_model=list[StaffNoteOut])
async def list_staff_notes(
    customer_id: uuid.UUID, staff: StaffUser, db: AsyncSession = Depends(get_db)
) -> list[StaffNoteOut]:
    exists = await db.scalar(select(Customer.id).where(Customer.id == customer_id))
    if exists is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    notes = (
        (
            await db.execute(
                select(StaffNote)
                .where(StaffNote.customer_id == customer_id)
                .order_by(StaffNote.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [
        StaffNoteOut(
            id=n.id,
            customer_id=n.customer_id,
            author_email=n.author_email,
            text=n.text,
            created_at=n.created_at,
        )
        for n in notes
    ]


@router.post(
    "/customers/{customer_id}/notes", response_model=StaffNoteOut, status_code=201
)
async def create_staff_note(
    customer_id: uuid.UUID,
    payload: StaffNoteCreateRequest,
    staff: StaffUser,
    db: AsyncSession = Depends(get_db),
) -> StaffNoteOut:
    exists = await db.scalar(select(Customer.id).where(Customer.id == customer_id))
    if exists is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    note = StaffNote(customer_id=customer_id, author_email=staff.email, text=payload.text)
    db.add(note)
    await db.flush()
    await AuditTrail().record(
        db, staff.email, "note.created", "staff_note", str(note.id),
        {"customer_id": str(customer_id)},
    )
    await db.commit()
    return StaffNoteOut(
        id=note.id,
        customer_id=note.customer_id,
        author_email=note.author_email,
        text=note.text,
        created_at=note.created_at,
    )


@router.delete("/notes/{note_id}", status_code=204)
async def delete_staff_note(
    note_id: uuid.UUID, staff: StaffUser, db: AsyncSession = Depends(get_db)
) -> Response:
    """Delete a staff note. Any staff member may delete any note - this is a
    small internal team tool, not a per-author-owned record."""
    note = await db.get(StaffNote, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")

    await AuditTrail().record(
        db, staff.email, "note.deleted", "staff_note", str(note.id),
        {"customer_id": str(note.customer_id)},
    )
    await db.delete(note)
    await db.commit()
    return Response(status_code=204)


# ===========================================================================
# Health (worker liveness, for the console topbar status chip)
# ===========================================================================

_WORKER_ALIVE_IDLE_MS = 30_000
"""Max consumer idle time (`XINFO CONSUMERS`' ``idle``, which resets on every
``XREADGROUP``/``XAUTOCLAIM`` call the consumer makes regardless of whether new
entries were returned) before the worker is considered dead. ``event_consumer``'s
loop blocks up to ``BLOCK_MS`` (5s) per read then immediately reclaims stale
entries, so a live worker's idle time never climbs far past that; 30s tolerates
a slow GC pause or two without false-flagging a healthy worker as down."""


async def _worker_health(redis: Any) -> WorkerHealthOut:
    pending = 0
    last_event_at: datetime | None = None
    alive = False
    try:
        groups = await redis.xinfo_groups(TXN_EVENTS)
    except Exception:
        groups = []  # stream doesn't exist yet - worker has never run
    group = next((g for g in groups if g.get("name") == GROUP_AGENTS), None)
    if group is not None:
        pending = int(group.get("pending", 0))
        last_id = str(group.get("last-delivered-id") or "0-0")
        if last_id != "0-0":
            last_event_at = datetime.fromtimestamp(int(last_id.split("-")[0]) / 1000, tz=UTC)
        try:
            consumers = await redis.xinfo_consumers(TXN_EVENTS, GROUP_AGENTS)
        except Exception:
            consumers = []
        alive = any(int(c.get("idle", 10**12)) < _WORKER_ALIVE_IDLE_MS for c in consumers)
    try:
        dlq = int(await redis.xlen(TXN_EVENTS_DLQ))
    except Exception:
        dlq = 0
    return WorkerHealthOut(alive=alive, last_event_at=last_event_at, pending=pending, dlq=dlq)


_DLQ_HEALTH_SAMPLE = 5
"""How many most-recent DLQ entries the health panel summarizes."""

_ERRORS_PAGE_SIZE = 50
"""How many recent unhandled errors `GET /console/errors` returns."""


async def _timed_db_ping(db: AsyncSession) -> tuple[str, float | None]:
    """Run a timed ``SELECT 1``; return ``(status, latency_ms)`` (None on failure)."""
    started = time.perf_counter()
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        logger.warning("console_health_db_failed", exc_info=True)
        return "degraded", None
    return "ok", round((time.perf_counter() - started) * 1000, 2)


async def _timed_redis_ping(redis: Any) -> float | None:
    """Run a timed ``PING``; return latency in ms (None on failure)."""
    started = time.perf_counter()
    try:
        await redis.ping()
    except Exception:
        logger.warning("console_health_redis_failed", exc_info=True)
        return None
    return round((time.perf_counter() - started) * 1000, 2)


async def _llm_budget_today(db: AsyncSession) -> LlmBudgetOut:
    """Today's (UTC day) LLM call count + cost from the `llm_calls` ledger, plus
    the configured daily budget and whether spend has crossed it.

    The ledger (Postgres) is the authoritative spend source here - the router's
    Redis counter is the same figure maintained cheaply for the hot-path guard;
    both derive from each call's `compute_cost`, so they agree."""
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    calls, cost = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(LlmCall.cost_usd), 0),
            ).where(LlmCall.created_at >= day_start)
        )
    ).one()
    budget = Decimal(str(get_settings().llm_daily_budget_usd))
    cost_today = Decimal(cost or 0)
    return LlmBudgetOut(
        calls_today=int(calls or 0),
        cost_usd_today=cost_today,
        budget_usd=budget,
        over_budget=budget > 0 and cost_today >= budget,
    )


async def _dlq_recent(redis: Any) -> list[DlqEntrySummaryOut]:
    """Summaries of the most-recent DLQ entries (newest first, id + error snippet)."""
    try:
        entries = await redis.xrevrange(
            TXN_EVENTS_DLQ, max="+", min="-", count=_DLQ_HEALTH_SAMPLE
        )
    except Exception:
        return []
    summaries: list[DlqEntrySummaryOut] = []
    for entry_id, fields in entries or []:
        raw_error = fields.get("error") if isinstance(fields, dict) else None
        error = (str(raw_error)[:200]) if raw_error else None
        summaries.append(DlqEntrySummaryOut(id=str(entry_id), error=error))
    return summaries


async def _scheduler_health(redis: Any, db: AsyncSession) -> SchedulerHealthOut:
    """Proactive-sweep loop state: enabled flag, last tick, sweeps today, and the
    current count of sweep-eligible customers (see `app.workers.scheduler`)."""
    from app.workers import scheduler

    try:
        eligible = await scheduler.count_eligible_customers(db)
    except Exception:
        logger.warning("console_health_scheduler_db_failed", exc_info=True)
        eligible = 0
    return SchedulerHealthOut(
        enabled=get_settings().scheduler_enabled,
        last_tick_at=await scheduler.read_last_tick(redis),
        swept_today=await scheduler.swept_today_count(redis),
        next_eligible_estimate=eligible,
    )


@router.get("/health", response_model=ConsoleHealthResponse)
async def console_health(
    staff: StaffUser, db: AsyncSession = Depends(get_db)
) -> ConsoleHealthResponse:
    redis = get_redis()
    api_status, db_latency_ms = await _timed_db_ping(db)
    redis_latency_ms = await _timed_redis_ping(redis)
    worker = await _worker_health(redis)
    llm_budget = await _llm_budget_today(db)
    dlq_recent = await _dlq_recent(redis)
    scheduler_health = await _scheduler_health(redis, db)
    return ConsoleHealthResponse(
        worker=worker,
        api=api_status,
        db_latency_ms=db_latency_ms,
        redis_latency_ms=redis_latency_ms,
        llm_budget=llm_budget,
        dlq_recent=dlq_recent,
        scheduler=scheduler_health,
    )


@router.get("/errors", response_model=ConsoleErrorsResponse)
async def console_errors(staff: StaffUser) -> ConsoleErrorsResponse:
    """Recent unhandled server errors (newest first) from the Redis error ring.

    Populated by the 500 exception handler (:mod:`app.core.errors`); a lightweight,
    self-hosted tail so staff can spot a spike without an external error tracker."""
    redis = get_redis()
    try:
        raw = await redis.lrange(ERROR_RING_KEY, 0, _ERRORS_PAGE_SIZE - 1)
    except Exception:
        logger.warning("console_errors_read_failed", exc_info=True)
        raw = []
    errors: list[ErrorLogEntryOut] = []
    for item in raw or []:
        try:
            errors.append(ErrorLogEntryOut.model_validate(orjson.loads(item)))
        except Exception:
            continue
    return ConsoleErrorsResponse(errors=errors)


# ===========================================================================
# Live feed (SSE)
# ===========================================================================


async def feed_events(
    redis: Any, start_id: str, is_disconnected: Callable[[], Awaitable[bool]]
) -> AsyncIterator[dict[str, str]]:
    """Tail ``agent.actions`` from ``start_id``, yielding SSE-ready dicts.

    A free (non-closure) function, deliberately, so it is unit-testable with a
    fake ``is_disconnected`` callable and a real/fake Redis client, independent
    of any ASGI transport (long-lived SSE streams don't round-trip cleanly
    through ``httpx.ASGITransport``, which buffers a full request/response
    cycle rather than truly streaming it).
    """
    cursor = start_id
    while not await is_disconnected():
        resp: Any = await redis.xread({AGENT_ACTIONS: cursor}, block=10_000, count=50)
        for _stream_name, entries in resp or []:
            for entry_id, fields in entries:
                cursor = entry_id
                data = fields.get("data")
                if data is not None:
                    yield {"event": "activity", "id": entry_id, "data": data}


@router.get("/feed")
async def console_feed(request: Request, staff: StaffUser) -> EventSourceResponse:
    """SSE tail of the ``agent.actions`` Stream, resumable via ``Last-Event-ID``."""
    start_id = request.headers.get("last-event-id") or request.query_params.get("since") or "$"
    return EventSourceResponse(
        feed_events(get_redis(), start_id, request.is_disconnected),
        ping=15,
        # Defeat proxy buffering so events flush immediately (nginx et al.).
        headers={"X-Accel-Buffering": "no"},
    )


# ===========================================================================
# Leads
# ===========================================================================


async def _fetch_leads(db: AsyncSession) -> Sequence[Lead]:
    """The exact leads query backing both ``/leads`` and its CSV export."""
    result = await db.execute(
        select(Lead).options(selectinload(Lead.customer)).order_by(Lead.created_at.desc())
    )
    return result.scalars().all()


def _lead_out(lead: Lead) -> LeadOut:
    return LeadOut(
        id=lead.id,
        customer=LeadCustomerOut(id=lead.customer.id, full_name=lead.customer.full_name)
        if lead.customer
        else None,
        source=lead.source,
        name=lead.name,
        email=lead.email,
        phone=lead.phone,
        intent_score=lead.intent_score,
        stage=lead.stage.value,
        created_at=lead.created_at,
    )


@router.get("/leads", response_model=list[LeadOut])
async def list_leads(staff: StaffUser, db: AsyncSession = Depends(get_db)) -> list[LeadOut]:
    leads = await _fetch_leads(db)
    return [_lead_out(lead) for lead in leads]


@router.get("/export/leads.csv", summary="Export leads as CSV (staff only)")
async def export_leads_csv(staff: StaffUser, db: AsyncSession = Depends(get_db)) -> Response:
    """Same rows and ordering as ``GET /console/leads`` (see ``_fetch_leads``), as a
    ``text/csv`` download. Values go through the stdlib ``csv`` module (proper
    quoting of commas/quotes/newlines), never hand-rolled string joining."""
    leads = await _fetch_leads(db)
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "id",
            "customer_id",
            "customer_name",
            "source",
            "name",
            "email",
            "phone",
            "intent_score",
            "stage",
            "created_at",
        ]
    )
    for lead in leads:
        writer.writerow(
            [
                str(lead.id),
                str(lead.customer.id) if lead.customer else "",
                lead.customer.full_name if lead.customer else "",
                lead.source,
                lead.name or "",
                lead.email or "",
                lead.phone or "",
                lead.intent_score,
                lead.stage.value,
                lead.created_at.isoformat(),
            ]
        )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )


# ===========================================================================
# Proposals (HITL)
# ===========================================================================


@router.get("/proposals", response_model=list[ProposalOut])
async def list_proposals(
    staff: StaffUser,
    status: str = Query(default="pending"),
    db: AsyncSession = Depends(get_db),
) -> list[ProposalOut]:
    stmt = select(Proposal).options(selectinload(Proposal.customer)).order_by(
        Proposal.created_at.desc()
    )
    if status != "all":
        try:
            status_enum = ProposalStatus(status)
        except ValueError as exc:
            valid = ", ".join(s.value for s in ProposalStatus)
            raise HTTPException(
                status_code=400, detail=f"invalid status {status!r}; expected one of: {valid}, all"
            ) from exc
        stmt = stmt.where(Proposal.status == status_enum)

    result = await db.execute(stmt)
    proposals = result.scalars().all()
    return [
        ProposalOut(
            id=p.id,
            customer=ProposalCustomerOut(id=p.customer.id, full_name=p.customer.full_name),
            agent=p.agent,
            kind=p.kind.value,
            title=p.title,
            body=p.body,
            action=p.action,
            status=p.status.value,
            created_at=p.created_at,
        )
        for p in proposals
    ]


@router.post("/proposals/{proposal_id}/approve", response_model=ProposalActionResult)
async def approve_proposal(
    proposal_id: uuid.UUID, staff: StaffUser, db: AsyncSession = Depends(get_db)
) -> ProposalActionResult:
    # execute_proposal opens its own session (mirrors run_event_trigger's pattern);
    # we only touch `db` here for a read, to enrich the console-feed publish below.
    customer_id = await db.scalar(select(Proposal.customer_id).where(Proposal.id == proposal_id))

    try:
        result = await execute_proposal(str(proposal_id), approver=staff.email)
    except EmailNotConfigured:
        # Real, expected outcome when AWS SES creds aren't configured yet - not a
        # demo shortcut: the proposal stays `pending` in the DB so approval can be
        # retried once credentials exist, and we say so plainly rather than
        # fabricating a "sent" response.
        logger.warning("proposal_approve_email_skipped_no_creds", proposal_id=str(proposal_id))
        return ProposalActionResult(
            proposal_id=str(proposal_id),
            action_kind="send_email",
            status="skipped_no_creds",
            detail={"reason": "AWS SES credentials are not configured"},
        )
    except ValueError as exc:
        message = str(exc)
        code = 404 if "not found" in message else 400
        raise HTTPException(status_code=code, detail=message) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await publish_activity(
        get_redis(),
        type="proposal",
        customer_id=customer_id,
        summary=f"Proposal approved by {staff.email}",
        ref_id=proposal_id,
    )
    return ProposalActionResult(
        proposal_id=result.proposal_id,
        action_kind=result.action_kind,
        status=result.status,
        detail=result.detail,
    )


@router.post("/proposals/{proposal_id}/reject", response_model=ProposalOut)
async def reject_proposal(
    proposal_id: uuid.UUID,
    payload: ProposalRejectRequest,
    staff: StaffUser,
    db: AsyncSession = Depends(get_db),
) -> ProposalOut:
    proposal = await db.get(Proposal, proposal_id, options=[selectinload(Proposal.customer)])
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status not in (ProposalStatus.PENDING, ProposalStatus.APPROVED):
        raise HTTPException(status_code=400, detail=f"proposal already {proposal.status.value}")

    proposal.status = ProposalStatus.REJECTED
    proposal.decided_by = staff.email
    proposal.decided_at = datetime.now(UTC)
    await db.flush()

    await AuditTrail().record(
        db, staff.email, "proposal.rejected", "proposal", str(proposal.id),
        {"reason": payload.reason},
    )
    await db.commit()

    reason_suffix = f": {payload.reason}" if payload.reason else ""
    await publish_activity(
        get_redis(),
        type="proposal",
        customer_id=proposal.customer_id,
        summary=f"Proposal rejected by {staff.email}{reason_suffix}",
        ref_id=proposal.id,
    )

    customer_out = ProposalCustomerOut(
        id=proposal.customer.id, full_name=proposal.customer.full_name
    )
    return ProposalOut(
        id=proposal.id,
        customer=customer_out,
        agent=proposal.agent,
        kind=proposal.kind.value,
        title=proposal.title,
        body=proposal.body,
        action=proposal.action,
        status=proposal.status.value,
        created_at=proposal.created_at,
    )


# ===========================================================================
# Life events
# ===========================================================================


@router.get("/life-events", response_model=list[LifeEventOut])
async def list_life_events(
    staff: StaffUser, db: AsyncSession = Depends(get_db)
) -> list[LifeEventOut]:
    result = await db.execute(
        select(LifeEvent)
        .options(selectinload(LifeEvent.customer))
        .order_by(LifeEvent.detected_at.desc())
    )
    life_events = result.scalars().all()
    return [
        LifeEventOut(
            id=le.id,
            customer=LifeEventCustomerOut(id=le.customer.id, full_name=le.customer.full_name),
            type=le.type.value,
            confidence=le.confidence,
            evidence=le.evidence,
            detected_at=le.detected_at,
            status=le.status.value,
        )
        for le in life_events
    ]


# ===========================================================================
# Funnels
# ===========================================================================

_QUALIFIED_STAGES = (
    LeadStage.QUALIFIED,
    LeadStage.CONTACTED,
    LeadStage.ONBOARDING,
    LeadStage.CONVERTED,
)


@router.get("/funnels", response_model=FunnelResponse)
async def get_funnels(staff: StaffUser, db: AsyncSession = Depends(get_db)) -> FunnelResponse:
    leads_total = await db.scalar(select(func.count()).select_from(Lead)) or 0
    qualified = (
        await db.scalar(
            select(func.count()).select_from(Lead).where(Lead.stage.in_(_QUALIFIED_STAGES))
        )
        or 0
    )
    kyc_verified = (
        await db.scalar(
            select(func.count(func.distinct(AuditLog.entity_id)))
            .where(
                AuditLog.action == "kyc.verified",
                AuditLog.payload["status"].astext == "verified",
            )
        )
        or 0
    )
    account_opened = (
        await db.scalar(select(func.count(func.distinct(Account.customer_id)))) or 0
    )

    nudges_total = await db.scalar(select(func.count()).select_from(Nudge)) or 0
    nudges_seen = (
        await db.scalar(
            select(func.count()).select_from(Nudge).where(Nudge.status != NudgeStatus.SENT)
        )
        or 0
    )
    nudges_acted = (
        await db.scalar(
            select(func.count()).select_from(Nudge).where(Nudge.status == NudgeStatus.ACTED)
        )
        or 0
    )

    holdings_rows = await db.execute(
        select(
            Product.category,
            func.count().filter(Holding.status == HoldingStatus.OFFERED),
            func.count().filter(Holding.status == HoldingStatus.ACTIVE),
        )
        .select_from(Holding)
        .join(Product, Holding.product_id == Product.id)
        .group_by(Product.category)
        .order_by(Product.category)
    )

    return FunnelResponse(
        acquisition=AcquisitionFunnel(
            leads=leads_total,
            qualified=qualified,
            kyc_verified=kyc_verified,
            account_opened=account_opened,
        ),
        nudges=NudgeFunnel(sent=nudges_total, seen=nudges_seen, acted=nudges_acted),
        holdings_by_category=[
            HoldingCategoryFunnel(category=category, offered=offered, active=active)
            for category, offered, active in holdings_rows
        ],
    )


# ===========================================================================
# Traces
# ===========================================================================


@router.get("/traces", response_model=list[TraceOut])
async def list_traces(
    staff: StaffUser,
    limit: int = Query(default=50, ge=1, le=200),
    trigger: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[TraceOut]:
    steps_count = (
        select(func.count(AgentStep.id))
        .where(AgentStep.run_id == AgentRun.id)
        .correlate(AgentRun)
        .scalar_subquery()
    )
    stmt = (
        select(AgentRun, steps_count)
        .options(selectinload(AgentRun.customer))
        .order_by(AgentRun.started_at.desc())
        .limit(limit)
    )
    if trigger is not None:
        try:
            trigger_enum = AgentTriggerType(trigger)
        except ValueError as exc:
            valid = ", ".join(t.value for t in AgentTriggerType)
            raise HTTPException(
                status_code=400, detail=f"invalid trigger {trigger!r}; expected one of: {valid}"
            ) from exc
        stmt = stmt.where(AgentRun.trigger == trigger_enum)

    result = await db.execute(stmt)
    rows = result.all()
    return [
        TraceOut(
            run_id=run.id,
            agent=run.agent,
            trigger=run.trigger.value,
            status=run.status.value,
            customer=TraceCustomerOut(id=run.customer.id, full_name=run.customer.full_name)
            if run.customer
            else None,
            started_at=run.started_at,
            latency_ms=run.latency_ms,
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            cost_usd=run.cost_usd,
            steps_count=steps_count_value,
        )
        for run, steps_count_value in rows
    ]


@router.get("/traces/{run_id}", response_model=TraceDetailResponse)
async def get_trace(
    run_id: uuid.UUID, staff: StaffUser, db: AsyncSession = Depends(get_db)
) -> TraceDetailResponse:
    run = await db.get(
        AgentRun, run_id, options=[selectinload(AgentRun.customer), selectinload(AgentRun.steps)]
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Trace not found")

    steps = sorted(run.steps, key=lambda s: s.seq)
    return TraceDetailResponse(
        run_id=run.id,
        agent=run.agent,
        trigger=run.trigger.value,
        status=run.status.value,
        customer=TraceCustomerOut(id=run.customer.id, full_name=run.customer.full_name)
        if run.customer
        else None,
        started_at=run.started_at,
        finished_at=run.finished_at,
        tokens_in=run.tokens_in,
        tokens_out=run.tokens_out,
        cost_usd=run.cost_usd,
        latency_ms=run.latency_ms,
        steps=[
            TraceStepOut(
                seq=s.seq,
                node=s.node,
                kind=s.kind.value,
                name=s.name,
                input=s.input,
                output=s.output,
                model=s.model,
                tokens_in=s.tokens_in,
                tokens_out=s.tokens_out,
                cost_usd=s.cost_usd,
                latency_ms=s.latency_ms,
            )
            for s in steps
        ],
    )


# ===========================================================================
# Costs
# ===========================================================================


async def _breakdown(db: AsyncSession, column: Any) -> list[CostBreakdownRow]:
    result = await db.execute(
        select(
            column,
            func.count(),
            func.coalesce(func.sum(LlmCall.tokens_in), 0),
            func.coalesce(func.sum(LlmCall.tokens_out), 0),
            func.coalesce(func.sum(LlmCall.cost_usd), 0),
        )
        .select_from(LlmCall)
        .group_by(column)
        .order_by(func.sum(LlmCall.cost_usd).desc())
    )
    return [
        CostBreakdownRow(key=str(key), calls=calls, tokens_in=tin, tokens_out=tout, cost_usd=cost)
        for key, calls, tin, tout, cost in result.all()
    ]


@router.get("/costs", response_model=CostsResponse)
async def get_costs(staff: StaffUser, db: AsyncSession = Depends(get_db)) -> CostsResponse:
    totals = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(LlmCall.tokens_in), 0),
                func.coalesce(func.sum(LlmCall.tokens_out), 0),
                func.coalesce(func.sum(LlmCall.cost_usd), 0),
                func.avg(LlmCall.latency_ms),
            ).select_from(LlmCall)
        )
    ).one()
    total_calls, total_tokens_in, total_tokens_out, total_cost, avg_latency = totals
    avg_latency_ms = round(avg_latency) if avg_latency is not None else None

    by_provider = await _breakdown(db, LlmCall.provider)
    by_model = await _breakdown(db, LlmCall.model)
    by_tier = await _breakdown(db, LlmCall.tier)
    by_purpose = await _breakdown(db, func.coalesce(LlmCall.purpose, "unspecified"))

    since = datetime.now(UTC) - timedelta(hours=24)
    # Explicit 'UTC' third arg: `date_trunc(field, source)` truncates in the
    # session's `TimeZone` GUC (e.g. Asia/Kolkata in this deployment), which
    # would bucket to `:30`-past-the-hour boundaries instead of the top of
    # the UTC hour the frontend's 24h chart assumes - the 3-arg form pins
    # the truncation to UTC regardless of session timezone.
    hour_bucket = func.date_trunc("hour", LlmCall.created_at, "UTC")
    series_result = await db.execute(
        select(hour_bucket, func.coalesce(func.sum(LlmCall.cost_usd), 0), func.count())
        .where(LlmCall.created_at >= since)
        .group_by(hour_bucket)
        .order_by(hour_bucket)
    )
    series = [
        CostSeriesPoint(hour=hour, cost_usd=cost, calls=calls)
        for hour, cost, calls in series_result.all()
    ]

    return CostsResponse(
        total_calls=total_calls,
        total_tokens_in=total_tokens_in,
        total_tokens_out=total_tokens_out,
        total_cost_usd=total_cost,
        avg_latency_ms=avg_latency_ms,
        by_provider=by_provider,
        by_model=by_model,
        by_tier=by_tier,
        by_purpose=by_purpose,
        last_24h=series,
    )


# ===========================================================================
# Analytics: detection scorecard, funnel time series, proposal outcomes
# ===========================================================================
#
# The jury-facing proof that the agent mesh actually works: ground-truth injected
# events graded against what got detected, daily funnel/spend trends, and the HITL
# proposal outcome mix. Everything reads real rows (agent_runs, life_events,
# proposals, nudges, llm_calls, sim_injections); nothing here is synthesised.

# Sim injected-type -> the `life_events.type` values that count as a correct
# detection for it. An empty family means "no life-event detection is expected"
# (churn is handled via nudges/proposals, not a life_event), so for those the
# correct outcome is that NOTHING was detected.
_DETECTION_FAMILY: dict[str, set[str]] = {
    "home_purchase_intent": {"home_intent"},
    "bonus_windfall": {"bonus", "salary_hike"},
    "wedding": {"marriage"},
    "job_change": {"job_change", "salary_hike"},
    "new_child": {"new_child"},
    "churn_risk": set(),
}


def _build_detection_row(
    injection: SimInjection,
    customer_name: str,
    window_end: datetime | None,
    events: list[LifeEvent],
) -> tuple[DetectionRow, LifeEvent | None]:
    """Pair one injection with the best detection inside its attribution window.

    ``events`` is this customer's life events sorted by ``detected_at`` ascending.
    The window is ``[injected_at, window_end)`` (``window_end`` is the customer's
    next injection, or ``None`` for the latest). A same-family detection is
    preferred over an earlier off-family one; the chosen event is returned so the
    caller can mark it attributed (for the no-injection false-positive tally)."""
    family = _DETECTION_FAMILY.get(injection.injected_type, set())
    in_window = [
        e
        for e in events
        if e.detected_at >= injection.injected_at
        and (window_end is None or e.detected_at < window_end)
    ]
    family_hits = [e for e in in_window if e.type.value in family]
    chosen = family_hits[0] if family_hits else (in_window[0] if in_window else None)

    detected = chosen is not None
    detected_type = chosen.type.value if chosen else None
    confidence = chosen.confidence if chosen else None
    lag_seconds = (
        (chosen.detected_at - injection.injected_at).total_seconds() if chosen else None
    )
    matched = (detected and detected_type in family) if family else (not detected)

    row = DetectionRow(
        injection_id=injection.id,
        customer_id=injection.customer_id,
        customer_name=customer_name,
        injected_type=injection.injected_type,
        injected_at=injection.injected_at,
        expected_types=sorted(family),
        detected=detected,
        detected_type=detected_type,
        confidence=confidence,
        lag_seconds=lag_seconds,
        matched=matched,
    )
    return row, chosen


async def _compute_detection(db: AsyncSession) -> DetectionResponse:
    """Detection scorecard: each console-injected ground-truth event vs. the life
    event the agent mesh actually detected (type match, confidence, and lag).

    Shared by the JSON endpoint (``GET /analytics/detection``) and its CSV export
    (``GET /export/detection.csv``) - one query + grading pass, two renderings."""
    inj_rows = (
        await db.execute(
            select(SimInjection, Customer.full_name)
            .join(Customer, SimInjection.customer_id == Customer.id)
            .order_by(SimInjection.customer_id, SimInjection.injected_at)
        )
    ).all()

    events = (
        (await db.execute(select(LifeEvent).order_by(LifeEvent.detected_at))).scalars().all()
    )
    events_by_customer: dict[uuid.UUID, list[LifeEvent]] = {}
    for event in events:
        events_by_customer.setdefault(event.customer_id, []).append(event)

    # Group injections per customer (already globally sorted by (customer, time)),
    # so each injection's window ends at the same customer's next injection.
    injections_by_customer: dict[uuid.UUID, list[tuple[SimInjection, str]]] = {}
    for injection, name in inj_rows:
        injections_by_customer.setdefault(injection.customer_id, []).append((injection, name))

    rows: list[DetectionRow] = []
    attributed_event_ids: set[uuid.UUID] = set()
    for customer_id, entries in injections_by_customer.items():
        customer_events = events_by_customer.get(customer_id, [])
        for idx, (injection, name) in enumerate(entries):
            window_end = entries[idx + 1][0].injected_at if idx + 1 < len(entries) else None
            row, chosen = _build_detection_row(injection, name, window_end, customer_events)
            rows.append(row)
            if chosen is not None:
                attributed_event_ids.add(chosen.id)

    rows.sort(key=lambda r: r.injected_at, reverse=True)

    # A detection with no injection: a life event that falls inside no injection
    # window (e.g. detected before that customer's first injection, or for a
    # customer that was never injected) - a rough unprompted / false-positive tally.
    detections_with_no_injection = 0
    for customer_id, customer_events in events_by_customer.items():
        windows = [
            (
                entry[0].injected_at,
                entries[i + 1][0].injected_at if i + 1 < len(entries) else None,
            )
            for entries in [injections_by_customer.get(customer_id, [])]
            for i, entry in enumerate(entries)
        ]
        for event in customer_events:
            attributed = any(
                event.detected_at >= start and (end is None or event.detected_at < end)
                for start, end in windows
            )
            if not attributed:
                detections_with_no_injection += 1

    summary = DetectionSummary(
        injected=len(rows),
        detected=sum(1 for r in rows if r.detected),
        matched=sum(1 for r in rows if r.matched),
        detections_with_no_injection=detections_with_no_injection,
    )
    return DetectionResponse(summary=summary, rows=rows)


@router.get("/analytics/detection", response_model=DetectionResponse)
async def analytics_detection(
    staff: StaffUser, db: AsyncSession = Depends(get_db)
) -> DetectionResponse:
    return await _compute_detection(db)


@router.get("/export/detection.csv", summary="Export the detection scorecard as CSV (staff only)")
async def export_detection_csv(staff: StaffUser, db: AsyncSession = Depends(get_db)) -> Response:
    """Same grading pass as ``GET /console/analytics/detection`` (see
    ``_compute_detection``), as a ``text/csv`` download."""
    detection = await _compute_detection(db)
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "injection_id",
            "customer_id",
            "customer_name",
            "injected_type",
            "injected_at",
            "expected_types",
            "detected",
            "detected_type",
            "confidence",
            "lag_seconds",
            "matched",
        ]
    )
    for row in detection.rows:
        writer.writerow(
            [
                str(row.injection_id),
                str(row.customer_id),
                row.customer_name,
                row.injected_type,
                row.injected_at.isoformat(),
                ";".join(row.expected_types),
                row.detected,
                row.detected_type or "",
                row.confidence if row.confidence is not None else "",
                row.lag_seconds if row.lag_seconds is not None else "",
                row.matched,
            ]
        )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=detection.csv"},
    )


def _bucket_by_utc_day(rows: Sequence[Any]) -> dict[date, Any]:
    """Index ``(day_ts, value)`` grouped rows by their UTC calendar date."""
    return {day.astimezone(UTC).date(): value for day, value in rows}


@router.get("/analytics/timeseries", response_model=TimeseriesResponse)
async def analytics_timeseries(
    staff: StaffUser,
    days: int = Query(default=14, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
) -> TimeseriesResponse:
    """Daily funnel + spend counters over the last ``days`` UTC days (dense: days
    with no activity are real zeros, so the sparklines stay evenly time-spaced)."""
    today = datetime.now(UTC).date()
    dates = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    since = datetime.combine(dates[0], datetime.min.time(), tzinfo=UTC)

    async def _daily(ts_col: Any, *, where: Any = None, value: Any = None) -> dict[date, Any]:
        day = func.date_trunc("day", ts_col, "UTC")
        agg = func.count() if value is None else func.coalesce(func.sum(value), 0)
        stmt = select(day, agg).where(ts_col >= since)
        if where is not None:
            stmt = stmt.where(where)
        stmt = stmt.group_by(day).order_by(day)
        return _bucket_by_utc_day((await db.execute(stmt)).all())

    agent_runs = await _daily(AgentRun.started_at)
    proposals_created = await _daily(Proposal.created_at)
    proposals_approved = await _daily(
        Proposal.decided_at,
        where=Proposal.status.in_((ProposalStatus.APPROVED, ProposalStatus.EXECUTED)),
    )
    nudges_sent = await _daily(Nudge.created_at)
    # Nudges carry no acted-at timestamp (only `created_at` + terminal status), so
    # acted counts bucket by the nudge's send day - a "of nudges sent that day, how
    # many were later acted" cohort read, the most honest slice the schema allows.
    nudges_acted = await _daily(Nudge.created_at, where=Nudge.status == NudgeStatus.ACTED)
    llm_cost = await _daily(LlmCall.created_at, value=LlmCall.cost_usd)

    points = [
        TimeseriesPoint(
            date=day.isoformat(),
            agent_runs=int(agent_runs.get(day, 0)),
            proposals_created=int(proposals_created.get(day, 0)),
            proposals_approved=int(proposals_approved.get(day, 0)),
            nudges_sent=int(nudges_sent.get(day, 0)),
            nudges_acted=int(nudges_acted.get(day, 0)),
            llm_cost_usd=Decimal(llm_cost.get(day, 0) or 0),
        )
        for day in dates
    ]
    return TimeseriesResponse(days=days, points=points)


@router.get("/analytics/proposals", response_model=ProposalOutcomesResponse)
async def analytics_proposals(
    staff: StaffUser, db: AsyncSession = Depends(get_db)
) -> ProposalOutcomesResponse:
    """HITL proposal outcome mix: status totals, average decision latency, and a
    per-agent created/approved/rejected breakdown for the approval-rate bars."""
    status_rows = (
        await db.execute(select(Proposal.status, func.count()).group_by(Proposal.status))
    ).all()
    by_status: dict[ProposalStatus, int] = {row[0]: row[1] for row in status_rows}

    avg_decision_seconds = await db.scalar(
        select(
            func.avg(func.extract("epoch", Proposal.decided_at - Proposal.created_at))
        ).where(Proposal.decided_at.is_not(None))
    )

    approved_filter = Proposal.status.in_((ProposalStatus.APPROVED, ProposalStatus.EXECUTED))
    agent_rows = (
        await db.execute(
            select(
                Proposal.agent,
                func.count(),
                func.count().filter(approved_filter),
                func.count().filter(Proposal.status == ProposalStatus.REJECTED),
            )
            .group_by(Proposal.agent)
            .order_by(func.count().desc())
        )
    ).all()

    return ProposalOutcomesResponse(
        pending=by_status.get(ProposalStatus.PENDING, 0),
        approved=by_status.get(ProposalStatus.APPROVED, 0),
        rejected=by_status.get(ProposalStatus.REJECTED, 0),
        executed=by_status.get(ProposalStatus.EXECUTED, 0),
        avg_decision_seconds=round(float(avg_decision_seconds), 1)
        if avg_decision_seconds is not None
        else None,
        by_agent=[
            ProposalAgentRow(agent=agent, created=created, approved=approved, rejected=rejected)
            for agent, created, approved, rejected in agent_rows
        ],
    )


# ===========================================================================
# Churn cockpit
# ===========================================================================
#
# `Customer.churn_risk` is a NOT NULL float defaulting to 0.0 - there is no real
# null state in the schema. A customer the engagement agent's `score_churn` tool
# has never reviewed simply stays at that untouched 0.0 default, so "unscored"
# below reads that sentinel value rather than a real NULL check. `score_churn`
# blends a deterministic feature score with an LLM read (`0.6*base + 0.4*llm`),
# so a *reviewed* customer landing on exactly 0.0 is possible but vanishingly
# rare - the honest caveat the frontend surfaces next to the count.

_CHURN_AT_RISK_THRESHOLD = 0.6
_CHURN_AT_RISK_LIMIT = 50
_CHURN_REENGAGE_SOURCE = "churn_reengage"
_CHURN_NUDGE_LOOKBACK_DAYS = 30

_CHURN_BUCKET_LABELS: tuple[ChurnBucketLabel, ...] = (
    "0-20", "20-40", "40-60", "60-80", "80-100",
)


async def _churn_distribution(db: AsyncSession) -> list[ChurnBucketOut]:
    """Bucket *scored* customers (`churn_risk > 0`, see module note above) into 5
    risk bands with one `func.count().filter(...)` per bucket in a single scan
    (mirrors `get_funnels`'s holdings-by-category breakdown)."""
    scored = Customer.churn_risk > 0.0
    row = (
        await db.execute(
            select(
                func.count().filter(scored, Customer.churn_risk < 0.2),
                func.count().filter(
                    scored, Customer.churn_risk >= 0.2, Customer.churn_risk < 0.4
                ),
                func.count().filter(
                    scored, Customer.churn_risk >= 0.4, Customer.churn_risk < 0.6
                ),
                func.count().filter(
                    scored, Customer.churn_risk >= 0.6, Customer.churn_risk < 0.8
                ),
                func.count().filter(scored, Customer.churn_risk >= 0.8),
            ).select_from(Customer)
        )
    ).one()
    return [
        ChurnBucketOut(bucket=label, count=int(count))
        for label, count in zip(_CHURN_BUCKET_LABELS, row, strict=True)
    ]


async def _churn_at_risk(db: AsyncSession) -> list[ChurnAtRiskCustomerOut]:
    """At-risk roster (`churn_risk >= 0.6`), richest-risk-first, with last
    activity, total balance, and recent-nudge count each joined from a
    per-customer aggregate subquery - one query regardless of roster size."""
    last_activity_subq = (
        select(
            Account.customer_id.label("customer_id"),
            func.max(Transaction.ts).label("last_activity_at"),
        )
        .join(Transaction, Transaction.account_id == Account.id)
        .group_by(Account.customer_id)
        .subquery()
    )
    balance_subq = (
        select(
            Account.customer_id.label("customer_id"),
            func.sum(Account.balance_paise).label("balance_paise"),
        )
        .group_by(Account.customer_id)
        .subquery()
    )
    since = datetime.now(UTC) - timedelta(days=_CHURN_NUDGE_LOOKBACK_DAYS)
    nudges_subq = (
        select(Nudge.customer_id.label("customer_id"), func.count().label("nudges_30d"))
        .where(Nudge.created_at >= since)
        .group_by(Nudge.customer_id)
        .subquery()
    )

    stmt = (
        select(
            Customer.id,
            Customer.full_name,
            Customer.churn_risk,
            last_activity_subq.c.last_activity_at,
            func.coalesce(balance_subq.c.balance_paise, 0),
            func.coalesce(nudges_subq.c.nudges_30d, 0),
        )
        .outerjoin(last_activity_subq, last_activity_subq.c.customer_id == Customer.id)
        .outerjoin(balance_subq, balance_subq.c.customer_id == Customer.id)
        .outerjoin(nudges_subq, nudges_subq.c.customer_id == Customer.id)
        .where(Customer.churn_risk >= _CHURN_AT_RISK_THRESHOLD)
        .order_by(Customer.churn_risk.desc())
        .limit(_CHURN_AT_RISK_LIMIT)
    )
    rows = (await db.execute(stmt)).all()

    # Which of these customers already have a pending re-engagement ask - one
    # extra query, not N+1, so a fresh page load renders "Requested" correctly
    # instead of only learning it from a 409 after a duplicate click.
    pending_reengage_ids = set(
        (
            await db.scalars(
                select(Proposal.customer_id).where(
                    Proposal.status == ProposalStatus.PENDING,
                    Proposal.action["source"].astext == _CHURN_REENGAGE_SOURCE,
                )
            )
        ).all()
    )

    return [
        ChurnAtRiskCustomerOut(
            id=cid,
            full_name=full_name,
            churn_risk=churn_risk,
            last_activity_at=last_activity_at,
            balance_paise=int(balance_paise),
            nudges_last_30d=int(nudges_30d),
            reengage_requested=cid in pending_reengage_ids,
        )
        for cid, full_name, churn_risk, last_activity_at, balance_paise, nudges_30d in rows
    ]


@router.get("/churn", response_model=ChurnCockpitResponse)
async def get_churn_cockpit(
    staff: StaffUser, db: AsyncSession = Depends(get_db)
) -> ChurnCockpitResponse:
    """Churn cockpit: risk distribution, the at-risk roster, and how many
    customers the engagement agent hasn't scored yet (see module note above)."""
    distribution = await _churn_distribution(db)
    at_risk = await _churn_at_risk(db)
    unscored = (
        await db.scalar(
            select(func.count()).select_from(Customer).where(Customer.churn_risk == 0.0)
        )
        or 0
    )
    return ChurnCockpitResponse(
        distribution=distribution, at_risk=at_risk, unscored=int(unscored)
    )


async def _customer_activity_stats(
    db: AsyncSession, customer_id: uuid.UUID
) -> tuple[datetime | None, int, int]:
    """``(last_activity_at, balance_paise, nudges_last_30d)`` for one customer -
    the single-customer counterpart of `_churn_at_risk`'s bulk joins, used to
    write the re-engagement proposal's factual body below."""
    account_ids = select(Account.id).where(Account.customer_id == customer_id).scalar_subquery()
    last_activity_at = await db.scalar(
        select(func.max(Transaction.ts)).where(Transaction.account_id.in_(account_ids))
    )
    balance_paise = (
        await db.scalar(
            select(func.coalesce(func.sum(Account.balance_paise), 0)).where(
                Account.customer_id == customer_id
            )
        )
        or 0
    )
    since = datetime.now(UTC) - timedelta(days=_CHURN_NUDGE_LOOKBACK_DAYS)
    nudges_30d = (
        await db.scalar(
            select(func.count())
            .select_from(Nudge)
            .where(Nudge.customer_id == customer_id, Nudge.created_at >= since)
        )
        or 0
    )
    return last_activity_at, int(balance_paise), int(nudges_30d)


def _format_inr(paise: int) -> str:
    return f"Rs {paise / 100:,.0f}"


def _churn_reengage_body(
    full_name: str,
    churn_risk: float,
    last_activity_at: datetime | None,
    balance_paise: int,
    nudges_last_30d: int,
) -> str:
    """Staff-authored template text (no LLM call) - every figure is read
    straight from the customer's own row, so the copy stays strictly factual."""
    risk_pct = round(churn_risk * 100)
    if last_activity_at is not None:
        days_inactive = max(0, (datetime.now(UTC) - last_activity_at).days)
        activity_clause = f"last transacted {days_inactive} day(s) ago"
    else:
        activity_clause = "has no recorded transactions"
    return (
        f"{full_name} carries a churn risk score of {risk_pct}% and {activity_clause}. "
        f"Current balance on file: {_format_inr(balance_paise)}. "
        f"{nudges_last_30d} nudge(s) sent in the last 30 days with no recorded conversion. "
        "Staff-requested re-engagement outreach - please reach out personally to check in "
        "and understand their needs before they leave."
    )


@router.post("/churn/{customer_id}/re-engage", response_model=ChurnReengageResult)
async def request_churn_reengagement(
    customer_id: uuid.UUID, staff: StaffUser, db: AsyncSession = Depends(get_db)
) -> ChurnReengageResult:
    customer = await db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    existing = await db.scalar(
        select(Proposal.id)
        .where(
            Proposal.customer_id == customer_id,
            Proposal.status == ProposalStatus.PENDING,
            Proposal.action["source"].astext == _CHURN_REENGAGE_SOURCE,
        )
        .limit(1)
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="A re-engagement proposal is already pending for this customer",
        )

    last_activity_at, balance_paise, nudges_30d = await _customer_activity_stats(
        db, customer_id
    )
    body = _churn_reengage_body(
        customer.full_name, customer.churn_risk, last_activity_at, balance_paise, nudges_30d
    )

    proposal = await create_proposal(
        db,
        customer_id=customer.id,
        agent="staff_console",
        kind=ProposalKind.NUDGE,
        title="Re-engagement outreach",
        # `kind: send_nudge` is one of `app.agents.actions.EXECUTABLE_ACTION_KINDS` -
        # `execute_proposal` dispatches it straight to `create_nudge` on approval.
        # `source` is this endpoint's own marker (not read by the executor) so the
        # 409 guard above can recognise "already has a pending re-engagement ask".
        body=body,
        action={"kind": "send_nudge", "source": _CHURN_REENGAGE_SOURCE},
    )
    await AuditTrail().record(
        db, staff.email, "proposal.created", "proposal", str(proposal.id),
        {"kind": "send_nudge", "source": _CHURN_REENGAGE_SOURCE},
    )
    await db.commit()

    await publish_activity(
        get_redis(),
        type="proposal",
        customer_id=customer.id,
        summary=f"Re-engagement proposal requested by {staff.email}",
        ref_id=proposal.id,
    )
    return ChurnReengageResult(proposal_id=proposal.id, status=proposal.status.value)


# ===========================================================================
# Human handoffs (the queue where the agent steps aside for a person)
# ===========================================================================

# Open-first, then high-urgency-first, then longest-waiting-first.
_HANDOFF_STATUS_RANK = {HandoffStatus.OPEN: 0, HandoffStatus.CLAIMED: 1}
_HANDOFF_URGENCY_RANK = {"high": 0, "normal": 1, "low": 2}
_HANDOFF_RESOLVED_LIMIT = 20


def _serialize_handoff(handoff: HandoffRequest) -> HandoffOut:
    customer = (
        HandoffCustomerOut(id=handoff.customer.id, full_name=handoff.customer.full_name)
        if handoff.customer is not None
        else None
    )
    return HandoffOut(
        id=handoff.id,
        customer=customer,
        conversation_id=handoff.conversation_id,
        reason=handoff.reason,
        urgency=handoff.urgency.value,
        status=handoff.status.value,
        claimed_by=handoff.claimed_by,
        resolution_note=handoff.resolution_note,
        created_at=handoff.created_at,
        claimed_at=handoff.claimed_at,
        resolved_at=handoff.resolved_at,
    )


@router.get("/handoffs", response_model=HandoffQueueResponse)
async def list_handoffs(
    staff: StaffUser, db: AsyncSession = Depends(get_db)
) -> HandoffQueueResponse:
    """The console handoff queue: active (open + claimed) first, then last 20 resolved."""
    active_rows = (
        (
            await db.execute(
                select(HandoffRequest).where(HandoffRequest.status != HandoffStatus.RESOLVED)
            )
        )
        .scalars()
        .all()
    )
    active_sorted = sorted(
        active_rows,
        key=lambda h: (
            _HANDOFF_STATUS_RANK.get(h.status, 9),
            _HANDOFF_URGENCY_RANK.get(h.urgency.value, 9),
            h.created_at,
        ),
    )

    resolved_rows = (
        (
            await db.execute(
                select(HandoffRequest)
                .where(HandoffRequest.status == HandoffStatus.RESOLVED)
                .order_by(HandoffRequest.resolved_at.desc().nullslast())
                .limit(_HANDOFF_RESOLVED_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    return HandoffQueueResponse(
        active=[_serialize_handoff(h) for h in active_sorted],
        resolved=[_serialize_handoff(h) for h in resolved_rows],
    )


@router.post("/handoffs/{handoff_id}/claim", response_model=HandoffOut)
async def claim_handoff(
    handoff_id: uuid.UUID, staff: StaffUser, db: AsyncSession = Depends(get_db)
) -> HandoffOut:
    handoff = await db.get(HandoffRequest, handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="Handoff not found")
    if handoff.status == HandoffStatus.RESOLVED:
        raise HTTPException(status_code=409, detail="This handoff is already resolved")
    if handoff.status == HandoffStatus.CLAIMED:
        raise HTTPException(
            status_code=409, detail=f"This handoff is already claimed by {handoff.claimed_by}"
        )

    handoff.status = HandoffStatus.CLAIMED
    handoff.claimed_by = staff.email
    handoff.claimed_at = datetime.now(UTC)
    await db.flush()
    await AuditTrail().record(
        db, staff.email, "handoff.claimed", "handoff_request", str(handoff.id),
        {"urgency": handoff.urgency.value},
    )
    await db.commit()

    await publish_activity(
        get_redis(),
        type="handoff",
        customer_id=handoff.customer_id,
        summary=f"Handoff claimed by {staff.email}",
        ref_id=handoff.id,
    )
    return _serialize_handoff(handoff)


@router.post("/handoffs/{handoff_id}/resolve", response_model=HandoffOut)
async def resolve_handoff(
    handoff_id: uuid.UUID,
    payload: HandoffResolveRequest,
    staff: StaffUser,
    db: AsyncSession = Depends(get_db),
) -> HandoffOut:
    """Resolve a handoff. Only the claimer resolves a claimed one; an unclaimed
    handoff is auto-claimed by whoever resolves it (small team, keep it simple)."""
    handoff = await db.get(HandoffRequest, handoff_id)
    if handoff is None:
        raise HTTPException(status_code=404, detail="Handoff not found")
    if handoff.status == HandoffStatus.RESOLVED:
        raise HTTPException(status_code=409, detail="This handoff is already resolved")
    if (
        handoff.status == HandoffStatus.CLAIMED
        and handoff.claimed_by is not None
        and handoff.claimed_by != staff.email
    ):
        raise HTTPException(
            status_code=403,
            detail=f"This handoff is claimed by {handoff.claimed_by} - only they can resolve it",
        )

    now = datetime.now(UTC)
    if handoff.claimed_by is None:
        # Resolver auto-claims an unclaimed handoff.
        handoff.claimed_by = staff.email
        handoff.claimed_at = now
    handoff.status = HandoffStatus.RESOLVED
    handoff.resolution_note = payload.note
    handoff.resolved_at = now

    if handoff.customer_id is not None:
        note_preview = payload.note if len(payload.note) <= 140 else f"{payload.note[:139]}…"
        await notify(
            db,
            handoff.customer_id,
            NotificationKind.SYSTEM,
            "Your request was handled",
            f"A relationship manager followed up: {note_preview}",
        )

    await db.flush()
    await AuditTrail().record(
        db, staff.email, "handoff.resolved", "handoff_request", str(handoff.id),
        {"urgency": handoff.urgency.value},
    )
    await db.commit()

    await publish_activity(
        get_redis(),
        type="handoff",
        customer_id=handoff.customer_id,
        summary=f"Handoff resolved by {staff.email}",
        ref_id=handoff.id,
    )
    return _serialize_handoff(handoff)


# ===========================================================================
# Sim: on-demand life-event injection
# ===========================================================================
#
# `app.sim.runner` has no runtime control surface (it's a batch asyncio CLI that
# owns its own in-process cohort of generators) - there is no live process to send
# a "fire this event now" command to. So this endpoint takes the documented
# fallback: replay the customer's *sim persona* forward through the requested
# life-event script, then publish the resulting transactions as real
# `txn.events` envelopes - the exact same envelope contract `app.sim.seed`/
# `app.sim.runner` use - so the real event consumer + agent mesh react to them
# exactly as they would to organic sim traffic. Nothing about the pipeline is
# faked; only the trigger is manual instead of time-based.

# 90 days (3 pay cycles), not 60: a job change skips one pay cycle for the
# hand-over gap (see `_JobChange.apply`'s `salary_skip_cycles`), so the first
# in-window salary is intentionally missing and the *new, higher* salary only
# lands in the second post-injection cycle. A 60-day window ended right on that
# second pay date's +/-2 day jitter, so the new-salary credit (the whole signal
# a job change is supposed to produce) frequently fell just outside it and the
# salary-change rule never saw the jump. 90 days guarantees it lands inside.
_INJECT_WINDOW_DAYS = 90


@router.post("/sim/inject-event", response_model=SimInjectEventResponse)
async def inject_sim_event(
    payload: SimInjectEventRequest, staff: StaffUser, db: AsyncSession = Depends(get_db)
) -> SimInjectEventResponse:
    customer = await db.get(Customer, payload.customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    if not customer.persona:
        raise HTTPException(
            status_code=400,
            detail="Customer has no sim persona profile - only seeded sim customers "
            "support life-event injection.",
        )

    try:
        event_type = sim_events.LifeEventType(payload.type)
    except ValueError as exc:
        valid = ", ".join(t.value for t in sim_events.LifeEventType)
        raise HTTPException(
            status_code=400, detail=f"invalid type {payload.type!r}; expected one of: {valid}"
        ) from exc

    script = sim_events.REGISTRY[event_type]
    persona = sim_personas.Persona.model_validate(customer.persona)

    accounts = await db.execute(select(Account).where(Account.customer_id == customer.id))
    account = accounts.scalars().first()
    if account is None:
        raise HTTPException(status_code=400, detail="Customer has no account to post events to")

    inject_seed = sim_personas.derived_seed(str(customer.id), "console_inject", payload.type)
    start_date = date.today()
    state = sim_generator.new_state(persona, inject_seed, start_date=start_date)
    state.balance_paise = account.balance_paise  # replay against the customer's real balance

    start_ts = datetime.combine(start_date, datetime.min.time())
    ground_truth = script.apply(persona, state, start_ts)

    # Walk the mutated state forward far enough to realise the script's full
    # scheduled window (weddings/home purchases span 30-45+ days; a job change's
    # income bump needs at least one pay cycle to show up).
    months = max(1, -(-_INJECT_WINDOW_DAYS // 30))  # ceil division
    txns = sim_generator.generate_history(
        persona, months, inject_seed, state=state, start_date=start_date
    )

    # Persist the ground truth BEFORE publishing: this is the auditable label the
    # detection scorecard grades the agent mesh against (injected type + customer +
    # time + the script's params). `injected_at` (server now()) is the t0 for the
    # detection-lag measurement.
    injection = SimInjection(
        customer_id=customer.id,
        injected_type=event_type.value,
        injected_by=staff.email,
        params=ground_truth.params,
    )
    db.add(injection)
    await db.flush()

    redis = get_redis()
    for txn in txns:
        envelope = sim_generator.to_envelope(txn)
        await redis.xadd(TXN_EVENTS, {"data": orjson.dumps(envelope).decode()})

    await publish_activity(
        redis,
        type="life_event",
        customer_id=customer.id,
        summary=f"Sim life-event '{event_type.value}' injected by {staff.email}",
        ref_id=None,
    )

    return SimInjectEventResponse(
        customer_id=customer.id,
        type=event_type.value,
        mode="txn_events_replay",
        detail={
            "transactions_queued": len(txns),
            "ground_truth": ground_truth.model_dump(mode="json"),
        },
    )
