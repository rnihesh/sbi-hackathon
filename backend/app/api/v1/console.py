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

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from app.agents.entrypoints import execute_proposal
from app.agents.guardrails import AuditTrail
from app.core.config import get_settings, is_staff_email
from app.core.db import get_db
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
from app.models.banking import Account
from app.models.catalog import Holding, Product
from app.models.crm import Lead
from app.models.customer import Customer
from app.models.engagement import LifeEvent, Nudge, Proposal
from app.models.enums import (
    AgentTriggerType,
    HoldingStatus,
    LeadStage,
    NudgeStatus,
    ProposalStatus,
)
from app.models.identity import User
from app.models.tracing import AgentRun, AgentStep, LlmCall
from app.schemas.console import (
    AcquisitionFunnel,
    ConsoleHealthResponse,
    CostBreakdownRow,
    CostSeriesPoint,
    CostsResponse,
    CustomerSearchOut,
    FunnelResponse,
    HoldingCategoryFunnel,
    LeadCustomerOut,
    LeadOut,
    LifeEventCustomerOut,
    LifeEventOut,
    NudgeFunnel,
    ProposalActionResult,
    ProposalCustomerOut,
    ProposalOut,
    ProposalRejectRequest,
    SimInjectEventRequest,
    SimInjectEventResponse,
    TraceCustomerOut,
    TraceDetailResponse,
    TraceOut,
    TraceStepOut,
    WorkerHealthOut,
)
from app.services.email import EmailNotConfigured
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


@router.get("/health", response_model=ConsoleHealthResponse)
async def console_health(
    staff: StaffUser, db: AsyncSession = Depends(get_db)
) -> ConsoleHealthResponse:
    try:
        await db.execute(select(1))
        api_status = "ok"
    except Exception:
        api_status = "degraded"
    worker = await _worker_health(get_redis())
    return ConsoleHealthResponse(worker=worker, api=api_status)


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


@router.get("/leads", response_model=list[LeadOut])
async def list_leads(staff: StaffUser, db: AsyncSession = Depends(get_db)) -> list[LeadOut]:
    result = await db.execute(
        select(Lead).options(selectinload(Lead.customer)).order_by(Lead.created_at.desc())
    )
    leads = result.scalars().all()
    return [
        LeadOut(
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
        for lead in leads
    ]


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
