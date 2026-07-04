"""Staff console API tests: staff gate, leads, proposals (HITL), life events,
funnels, traces, costs, and the sim life-event injector.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import TXN_EVENTS, get_redis
from app.models.banking import Account, Transaction
from app.models.catalog import Holding, Product
from app.models.crm import Lead
from app.models.customer import Customer
from app.models.engagement import LifeEvent, Notification, Nudge, Proposal
from app.models.enums import (
    AccountStatus,
    AccountType,
    AgentRunStatus,
    AgentTriggerType,
    DigitalMaturity,
    HoldingStatus,
    LeadStage,
    LifeEventStatus,
    LifeEventType,
    LlmTier,
    NotificationKind,
    NudgeStatus,
    ProposalKind,
    ProposalStatus,
    TxnChannel,
    TxnDirection,
)
from app.models.identity import User
from app.models.tracing import AgentRun, LlmCall
from tests.api.conftest import auth_cookies


async def _staff_user(
    make_customer: Callable[..., Any], set_staff_emails: Callable[[str], None]
) -> tuple[User, Customer]:
    user, customer = await make_customer(email="staff-console@example.com")
    set_staff_emails("staff-console@example.com")
    return user, customer


async def test_non_staff_gets_403(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    user, _customer = await make_customer(email="regular@example.com")
    set_staff_emails("someone-else@example.com")
    resp = await client.get("/api/v1/console/leads", cookies=auth_cookies(user))
    assert resp.status_code == 403


async def test_staff_gets_200(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    user, _customer = await _staff_user(make_customer, set_staff_emails)
    resp = await client.get("/api/v1/console/leads", cookies=auth_cookies(user))
    assert resp.status_code == 200


async def test_list_leads(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff_user, _sc = await _staff_user(make_customer, set_staff_emails)
    _u, customer = await make_customer(email="leadcust@example.com")
    db.add(
        Lead(
            customer_id=customer.id, source="chat", name=customer.full_name,
            intent_score=0.7, stage=LeadStage.QUALIFIED,
        )
    )
    await db.commit()

    resp = await client.get("/api/v1/console/leads", cookies=auth_cookies(staff_user))
    assert resp.status_code == 200
    leads = resp.json()
    assert len(leads) == 1
    assert leads[0]["customer"]["id"] == str(customer.id)
    assert leads[0]["stage"] == "qualified"


async def test_proposals_default_pending_filter(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff_user, _sc = await _staff_user(make_customer, set_staff_emails)
    _u, customer = await make_customer(email="propcust@example.com")
    pending = Proposal(
        customer_id=customer.id, agent="adoption", kind=ProposalKind.NUDGE,
        title="Pending one", body="b", action={"kind": "send_nudge"},
        status=ProposalStatus.PENDING,
    )
    executed = Proposal(
        customer_id=customer.id, agent="adoption", kind=ProposalKind.NUDGE,
        title="Executed one", body="b", action={"kind": "send_nudge"},
        status=ProposalStatus.EXECUTED,
    )
    db.add_all([pending, executed])
    await db.commit()

    resp = await client.get("/api/v1/console/proposals", cookies=auth_cookies(staff_user))
    assert resp.status_code == 200
    titles = [p["title"] for p in resp.json()]
    assert titles == ["Pending one"]

    resp_all = await client.get(
        "/api/v1/console/proposals", params={"status": "all"}, cookies=auth_cookies(staff_user)
    )
    assert len(resp_all.json()) == 2


async def test_approve_nudge_proposal_executes(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff_user, _sc = await _staff_user(make_customer, set_staff_emails)
    _u, customer = await make_customer(email="approvecust@example.com")
    proposal = Proposal(
        customer_id=customer.id, agent="adoption", kind=ProposalKind.NUDGE,
        title="Set up UPI", body="You should try UPI", action={"kind": "send_nudge"},
        status=ProposalStatus.PENDING,
    )
    db.add(proposal)
    await db.commit()

    resp = await client.post(
        f"/api/v1/console/proposals/{proposal.id}/approve", cookies=auth_cookies(staff_user)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "executed"
    assert "nudge_id" in body["detail"]

    nudges = (await db.execute(sa.select(Nudge))).scalars().all()
    assert len(nudges) == 1


async def test_approve_email_proposal_skipped_without_creds(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "aws_access_key_id", None)
    monkeypatch.setattr(get_settings(), "aws_secret_access_key", None)

    staff_user, _sc = await _staff_user(make_customer, set_staff_emails)
    _u, customer = await make_customer(email="emailcust@example.com")
    proposal = Proposal(
        customer_id=customer.id, agent="engagement", kind=ProposalKind.EMAIL,
        title="Congrats", body="body",
        action={
            "kind": "send_email",
            "to": customer.email,
            "template_name": "proposal_outreach",
            "context": {
                "title": "Congrats",
                "full_name": customer.full_name,
                "event_headline": "Congrats on the news!",
                "body": "body",
                "cta_url": None,
                "cta_label": None,
            },
        },
        status=ProposalStatus.PENDING,
    )
    db.add(proposal)
    await db.commit()

    resp = await client.post(
        f"/api/v1/console/proposals/{proposal.id}/approve", cookies=auth_cookies(staff_user)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "skipped_no_creds"

    await db.refresh(proposal)
    assert proposal.status == ProposalStatus.PENDING


async def test_reject_proposal(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff_user, _sc = await _staff_user(make_customer, set_staff_emails)
    _u, customer = await make_customer(email="rejectcust@example.com")
    proposal = Proposal(
        customer_id=customer.id, agent="adoption", kind=ProposalKind.NUDGE,
        title="Not now", body="b", action={"kind": "send_nudge"}, status=ProposalStatus.PENDING,
    )
    db.add(proposal)
    await db.commit()

    resp = await client.post(
        f"/api/v1/console/proposals/{proposal.id}/reject",
        json={"reason": "not relevant"},
        cookies=auth_cookies(staff_user),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


async def test_list_life_events(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff_user, _sc = await _staff_user(make_customer, set_staff_emails)
    _u, customer = await make_customer(email="lifecust@example.com")
    db.add(
        LifeEvent(
            customer_id=customer.id, type=LifeEventType.JOB_CHANGE, confidence=0.8,
            evidence={"note": "raise"}, status=LifeEventStatus.DETECTED,
        )
    )
    await db.commit()

    resp = await client.get("/api/v1/console/life-events", cookies=auth_cookies(staff_user))
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) == 1
    assert events[0]["type"] == "job_change"


async def test_funnels_aggregates(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff_user, _sc = await _staff_user(make_customer, set_staff_emails)
    _u, customer = await make_customer(email="funnelcust@example.com")
    db.add(
        Lead(customer_id=customer.id, source="chat", stage=LeadStage.QUALIFIED, intent_score=0.7)
    )
    db.add(
        Account(
            customer_id=customer.id, type=AccountType.SAVINGS,
            balance_paise=100_00, status=AccountStatus.ACTIVE,
        )
    )
    db.add(Nudge(customer_id=customer.id, title="n1", body="b", status=NudgeStatus.SEEN))
    await db.commit()

    resp = await client.get("/api/v1/console/funnels", cookies=auth_cookies(staff_user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["acquisition"]["leads"] == 1
    assert body["acquisition"]["qualified"] == 1
    assert body["acquisition"]["account_opened"] == 1
    assert body["nudges"]["sent"] == 1
    assert body["nudges"]["seen"] == 1


async def test_traces_list_and_detail(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff_user, _sc = await _staff_user(make_customer, set_staff_emails)
    _u, customer = await make_customer(email="tracecust@example.com")
    run = AgentRun(
        agent="supervisor", trigger=AgentTriggerType.CHAT, status=AgentRunStatus.COMPLETED,
        customer_id=customer.id, tokens_in=10, tokens_out=5,
    )
    db.add(run)
    await db.commit()

    list_resp = await client.get("/api/v1/console/traces", cookies=auth_cookies(staff_user))
    assert list_resp.status_code == 200
    traces = list_resp.json()
    assert len(traces) == 1
    assert traces[0]["run_id"] == str(run.id)
    assert traces[0]["steps_count"] == 0

    detail_resp = await client.get(
        f"/api/v1/console/traces/{run.id}", cookies=auth_cookies(staff_user)
    )
    assert detail_resp.status_code == 200
    assert detail_resp.json()["steps"] == []

    missing_resp = await client.get(
        f"/api/v1/console/traces/{uuid.uuid4()}", cookies=auth_cookies(staff_user)
    )
    assert missing_resp.status_code == 404


async def test_costs_aggregates(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff_user, _sc = await _staff_user(make_customer, set_staff_emails)
    db.add(
        LlmCall(
            provider="openai", model="gpt-4.1-mini", tier=LlmTier.FAST,
            tokens_in=100, tokens_out=50, cost_usd=Decimal("0.001"), ok=True,
            purpose="supervisor:classify", latency_ms=400,
        )
    )
    await db.commit()

    resp = await client.get("/api/v1/console/costs", cookies=auth_cookies(staff_user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_calls"] == 1
    assert body["total_tokens_in"] == 100
    assert body["avg_latency_ms"] == 400
    assert any(row["key"] == "openai" for row in body["by_provider"])


async def test_costs_avg_latency_null_when_no_calls(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff_user, _sc = await _staff_user(make_customer, set_staff_emails)

    resp = await client.get("/api/v1/console/costs", cookies=auth_cookies(staff_user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_calls"] == 0
    assert body["avg_latency_ms"] is None


async def test_sim_inject_event_validates_customer_and_persona(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff_user, _sc = await _staff_user(make_customer, set_staff_emails)

    missing_resp = await client.post(
        "/api/v1/console/sim/inject-event",
        json={"customer_id": str(uuid.uuid4()), "type": "job_change"},
        cookies=auth_cookies(staff_user),
    )
    assert missing_resp.status_code == 404

    _u, no_persona_customer = await make_customer(email="nopersona@example.com")
    no_persona_resp = await client.post(
        "/api/v1/console/sim/inject-event",
        json={"customer_id": str(no_persona_customer.id), "type": "job_change"},
        cookies=auth_cookies(staff_user),
    )
    assert no_persona_resp.status_code == 400


async def test_sim_inject_event_publishes_to_txn_events(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    from app.sim import personas as sim_personas

    staff_user, _sc = await _staff_user(make_customer, set_staff_emails)
    _u, customer = await make_customer(email="injectcust@example.com")

    cohort = sim_personas.make_cohort(1, seed=7)
    persona = cohort[0]
    customer.persona = persona.model_dump(mode="json")
    db.add(
        Account(
            customer_id=customer.id, type=AccountType.SAVINGS,
            balance_paise=500_000_00, status=AccountStatus.ACTIVE,
        )
    )
    await db.commit()

    redis = get_redis()
    before = await redis.xlen(TXN_EVENTS)

    resp = await client.post(
        "/api/v1/console/sim/inject-event",
        json={"customer_id": str(customer.id), "type": "bonus_windfall"},
        cookies=auth_cookies(staff_user),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "txn_events_replay"
    assert body["detail"]["transactions_queued"] > 0

    after = await redis.xlen(TXN_EVENTS)
    assert after > before


async def test_search_customers_requires_staff(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer(email="search-non-staff@example.com")
    resp = await client.get("/api/v1/console/customers", cookies=auth_cookies(user))
    assert resp.status_code == 403


async def test_search_customers_filters_by_name(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff_user, _sc = await _staff_user(make_customer, set_staff_emails)
    await make_customer(email="alice@example.com", full_name="Alice Sharma")
    await make_customer(email="bob@example.com", full_name="Bob Verma")

    resp = await client.get(
        "/api/v1/console/customers", params={"q": "ali"}, cookies=auth_cookies(staff_user)
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert [r["full_name"] for r in rows] == ["Alice Sharma"]
    assert set(rows[0].keys()) == {"id", "full_name", "city"}


async def test_search_customers_no_query_returns_recent_up_to_limit(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff_user, _sc = await _staff_user(make_customer, set_staff_emails)
    for i in range(3):
        await make_customer(email=f"cust{i}@example.com", full_name=f"Customer {i}")

    resp = await client.get(
        "/api/v1/console/customers", params={"limit": 2}, cookies=auth_cookies(staff_user)
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_health_requires_staff(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer(email="health-non-staff@example.com")
    resp = await client.get("/api/v1/console/health", cookies=auth_cookies(user))
    assert resp.status_code == 403


async def test_health_no_worker_ever_started(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff_user, _sc = await _staff_user(make_customer, set_staff_emails)
    resp = await client.get("/api/v1/console/health", cookies=auth_cookies(staff_user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["api"] == "ok"
    assert body["worker"] == {
        "alive": False, "last_event_at": None, "pending": 0, "dlq": 0,
    }


async def test_health_reports_alive_worker_from_consumer_group(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    from app.core.redis import GROUP_AGENTS, TXN_EVENTS

    staff_user, _sc = await _staff_user(make_customer, set_staff_emails)
    redis = get_redis()
    await redis.xadd(TXN_EVENTS, {"data": "{}"})
    await redis.xgroup_create(TXN_EVENTS, GROUP_AGENTS, id="0")
    await redis.xreadgroup(GROUP_AGENTS, "consumer-1", {TXN_EVENTS: ">"}, count=10)

    resp = await client.get("/api/v1/console/health", cookies=auth_cookies(staff_user))
    assert resp.status_code == 200
    body = resp.json()
    assert body["worker"]["alive"] is True
    assert body["worker"]["last_event_at"] is not None
    assert body["worker"]["pending"] == 1


async def test_health_alive_false_when_consumer_idle_exceeds_threshold(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.redis import GROUP_AGENTS, TXN_EVENTS

    staff_user, _sc = await _staff_user(make_customer, set_staff_emails)
    redis = get_redis()
    await redis.xadd(TXN_EVENTS, {"data": "{}"})
    await redis.xgroup_create(TXN_EVENTS, GROUP_AGENTS, id="0")
    await redis.xreadgroup(GROUP_AGENTS, "consumer-1", {TXN_EVENTS: ">"}, count=10)

    # The consumer's `idle` is genuinely ~0ms right after the read above; force
    # the "still counts as alive" threshold below that so the comparison branch
    # that flags a stalled worker is exercised without a real-time sleep.
    import app.api.v1.console as console_module

    monkeypatch.setattr(console_module, "_WORKER_ALIVE_IDLE_MS", -1)

    resp = await client.get("/api/v1/console/health", cookies=auth_cookies(staff_user))
    assert resp.status_code == 200
    assert resp.json()["worker"]["alive"] is False


async def test_health_reports_dlq_count(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    from app.core.redis import TXN_EVENTS_DLQ

    staff_user, _sc = await _staff_user(make_customer, set_staff_emails)
    redis = get_redis()
    await redis.xadd(TXN_EVENTS_DLQ, {"data": "{}", "error": "boom"})

    resp = await client.get("/api/v1/console/health", cookies=auth_cookies(staff_user))
    assert resp.status_code == 200
    assert resp.json()["worker"]["dlq"] == 1


async def test_feed_requires_staff(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer(email="feed-non-staff@example.com")
    resp = await client.get("/api/v1/console/feed", cookies=auth_cookies(user))
    assert resp.status_code == 403


async def test_feed_events_yields_published_activity() -> None:
    """Exercises the feed's polling logic directly.

    `httpx.ASGITransport` buffers a full ASGI request/response cycle rather
    than truly streaming it, so it cannot drive a genuinely long-lived SSE
    endpoint like `/console/feed` end-to-end in-process; `app.api.v1.console`
    factors the polling loop out into the free function `feed_events` for
    exactly this reason (see its docstring), which this test drives directly.
    """
    from app.workers.activity import publish_activity

    redis = get_redis()
    await publish_activity(
        redis, type="nudge", customer_id=None, summary="hello from the feed", ref_id="abc"
    )

    from app.api.v1.console import feed_events

    calls = 0

    async def is_disconnected() -> bool:
        nonlocal calls
        calls += 1
        return calls > 1  # let exactly one poll iteration run, then stop

    events = [event async for event in feed_events(redis, "0", is_disconnected)]
    assert any("hello from the feed" in e["data"] for e in events)


# ===========================================================================
# Customer 360 (detail + timeline)
# ===========================================================================


async def test_customer_detail_requires_staff(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, target = await make_customer(email="detail-non-staff@example.com")
    resp = await client.get(f"/api/v1/console/customers/{target.id}", cookies=auth_cookies(user))
    assert resp.status_code == 403


async def test_customer_detail_404_for_unknown_id(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff_user, _sc = await _staff_user(make_customer, set_staff_emails)
    resp = await client.get(
        f"/api/v1/console/customers/{uuid.uuid4()}", cookies=auth_cookies(staff_user)
    )
    assert resp.status_code == 404


async def test_customer_detail_returns_profile_accounts_holdings_stats(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff_user, _sc = await _staff_user(make_customer, set_staff_emails)
    _u, customer = await make_customer(
        email="detailcust@example.com",
        full_name="Detail Customer",
        phone="9876543210",
        city="Mumbai",
        segment="premium",
        digital_maturity=DigitalMaturity.HIGH,
        churn_risk=0.42,
        preferred_language="hi",
    )

    account = Account(
        customer_id=customer.id, type=AccountType.SAVINGS,
        balance_paise=150_000, status=AccountStatus.ACTIVE,
    )
    db.add(account)
    await db.flush()  # need account.id for the transactions below

    product = Product(code="MF001", name="Equity Growth Fund", category="mutual_fund")
    db.add(product)
    await db.flush()  # need product.id for the holding below
    db.add(Holding(customer_id=customer.id, product_id=product.id, status=HoldingStatus.ACTIVE))

    now = datetime.now(UTC)
    db.add(
        Transaction(
            account_id=account.id, ts=now - timedelta(days=5), amount_paise=50_00,
            direction=TxnDirection.DEBIT, channel=TxnChannel.UPI, balance_after_paise=100_000,
        )
    )
    db.add(
        Transaction(
            # Outside the 90-day stats window - must not count.
            account_id=account.id, ts=now - timedelta(days=200), amount_paise=20_00,
            direction=TxnDirection.CREDIT, channel=TxnChannel.NEFT, balance_after_paise=120_000,
        )
    )
    db.add(
        AgentRun(
            agent="engagement", trigger=AgentTriggerType.EVENT, status=AgentRunStatus.COMPLETED,
            customer_id=customer.id, tokens_in=10, tokens_out=5, cost_usd=Decimal("0.002"),
        )
    )
    db.add(
        Proposal(
            customer_id=customer.id, agent="engagement", kind=ProposalKind.NUDGE,
            title="p1", body="b", action={"kind": "send_nudge"}, status=ProposalStatus.PENDING,
        )
    )
    db.add(Nudge(customer_id=customer.id, title="n1", body="b", status=NudgeStatus.SENT))
    db.add(
        LifeEvent(
            customer_id=customer.id, type=LifeEventType.JOB_CHANGE, confidence=0.7,
            evidence={}, status=LifeEventStatus.DETECTED,
        )
    )
    await db.commit()

    resp = await client.get(
        f"/api/v1/console/customers/{customer.id}", cookies=auth_cookies(staff_user)
    )
    assert resp.status_code == 200
    body = resp.json()

    assert body["customer"]["id"] == str(customer.id)
    assert body["customer"]["full_name"] == "Detail Customer"
    assert body["customer"]["phone"] == "9876543210"
    assert body["customer"]["city"] == "Mumbai"
    assert body["customer"]["segment"] == "premium"
    assert body["customer"]["digital_maturity"] == "high"
    assert body["customer"]["churn_risk"] == pytest.approx(0.42)
    assert body["customer"]["preferred_language"] == "hi"

    assert body["accounts"] == [{"type": "savings", "balance_paise": 150_000, "status": "active"}]
    assert body["holdings"] == [
        {
            "product": {"code": "MF001", "name": "Equity Growth Fund", "category": "mutual_fund"},
            "status": "active",
        }
    ]
    assert body["stats"] == {
        "transactions_90d": 1,
        "agent_runs_total": 1,
        "proposals_pending": 1,
        "nudges_sent": 1,
        "life_events": 1,
    }


async def test_customer_timeline_requires_staff(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, target = await make_customer(email="timeline-non-staff@example.com")
    resp = await client.get(
        f"/api/v1/console/customers/{target.id}/timeline", cookies=auth_cookies(user)
    )
    assert resp.status_code == 403


async def test_customer_timeline_404_for_unknown_id(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff_user, _sc = await _staff_user(make_customer, set_staff_emails)
    resp = await client.get(
        f"/api/v1/console/customers/{uuid.uuid4()}/timeline", cookies=auth_cookies(staff_user)
    )
    assert resp.status_code == 404


async def _seed_one_of_each_timeline_type(
    db: AsyncSession, customer: Customer, now: datetime
) -> None:
    """One row per timeline source type, each 1 second apart, oldest to newest:
    notification, nudge, proposal, life_event, agent_run."""
    db.add(
        Notification(
            customer_id=customer.id, kind=NotificationKind.OFFER, title="Offer notif",
            body="b", created_at=now - timedelta(seconds=4),
        )
    )
    db.add(
        Nudge(
            customer_id=customer.id, title="Nudge title", body="b", status=NudgeStatus.SENT,
            created_at=now - timedelta(seconds=3),
        )
    )
    db.add(
        Proposal(
            customer_id=customer.id, agent="engagement", kind=ProposalKind.NUDGE,
            title="Proposal title", body="b", action={"kind": "send_nudge"},
            status=ProposalStatus.PENDING, created_at=now - timedelta(seconds=2),
        )
    )
    db.add(
        LifeEvent(
            customer_id=customer.id, type=LifeEventType.NEW_CHILD, confidence=0.9, evidence={},
            status=LifeEventStatus.DETECTED, detected_at=now - timedelta(seconds=1),
        )
    )
    db.add(
        AgentRun(
            agent="supervisor", trigger=AgentTriggerType.CHAT, status=AgentRunStatus.COMPLETED,
            customer_id=customer.id, tokens_in=1, tokens_out=1, cost_usd=Decimal("0.001"),
            started_at=now,
        )
    )
    await db.commit()


async def test_customer_timeline_merges_all_types_sorted_desc(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff_user, _sc = await _staff_user(make_customer, set_staff_emails)
    _u, customer = await make_customer(email="timelinecust@example.com")
    now = datetime.now(UTC)
    await _seed_one_of_each_timeline_type(db, customer, now)

    resp = await client.get(
        f"/api/v1/console/customers/{customer.id}/timeline", cookies=auth_cookies(staff_user)
    )
    assert resp.status_code == 200
    items = resp.json()

    assert [item["type"] for item in items] == [
        "agent_run", "life_event", "proposal", "nudge", "notification",
    ]
    # Newest-first: each item's ts is >= the next one's.
    timestamps = [item["ts"] for item in items]
    assert timestamps == sorted(timestamps, reverse=True)

    agent_run_data = items[0]["data"]
    assert agent_run_data["agent"] == "supervisor"
    assert agent_run_data["status"] == "completed"
    assert Decimal(agent_run_data["cost_usd"]) == Decimal("0.001")
    assert "run_id" in agent_run_data

    life_event_data = items[1]["data"]
    assert life_event_data["type"] == "new_child"
    assert life_event_data["confidence"] == 0.9
    assert "detected_at" in life_event_data

    proposal_data = items[2]["data"]
    assert proposal_data["title"] == "Proposal title"
    assert proposal_data["status"] == "pending"
    assert proposal_data["decided_at"] is None

    nudge_data = items[3]["data"]
    assert nudge_data["title"] == "Nudge title"
    assert nudge_data["status"] == "sent"

    notification_data = items[4]["data"]
    assert notification_data["kind"] == "offer"
    assert notification_data["title"] == "Offer notif"


async def test_customer_timeline_limit_applied_after_merge(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    """A cross-type `limit` cut proves the merge happens before the limit is
    applied - naively limiting each source first and concatenating would still
    pass `test_customer_timeline_merges_all_types_sorted_desc` (only 1 row per
    source there) but would fail this: the 3 newest rows here span 3 different
    source types, so a per-source-only limit could accidentally keep a stale
    older row from one type instead of a newer row from another."""
    staff_user, _sc = await _staff_user(make_customer, set_staff_emails)
    _u, customer = await make_customer(email="timelinelimitcust@example.com")
    now = datetime.now(UTC)
    await _seed_one_of_each_timeline_type(db, customer, now)

    resp = await client.get(
        f"/api/v1/console/customers/{customer.id}/timeline",
        params={"limit": 3},
        cookies=auth_cookies(staff_user),
    )
    assert resp.status_code == 200
    items = resp.json()
    assert [item["type"] for item in items] == ["agent_run", "life_event", "proposal"]
