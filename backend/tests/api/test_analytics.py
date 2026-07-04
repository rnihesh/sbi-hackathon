"""Console analytics tests: detection scorecard, funnel time series, proposal
outcomes, the health budget fields, and inject-event ground-truth persistence.

Runs against the real ``sarathi_test`` DB (see ``tests/api/conftest.py``); every
row is crafted, nothing is faked.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import TXN_EVENTS, get_redis
from app.models.banking import Account
from app.models.engagement import LifeEvent, Nudge, Proposal
from app.models.enums import (
    AccountStatus,
    AccountType,
    AgentRunStatus,
    AgentTriggerType,
    LifeEventStatus,
    LifeEventType,
    LlmTier,
    NudgeStatus,
    ProposalKind,
    ProposalStatus,
)
from app.models.identity import User
from app.models.sim_injection import SimInjection
from app.models.tracing import AgentRun, LlmCall
from tests.api.conftest import auth_cookies


async def _staff(
    make_customer: Callable[..., Any], set_staff_emails: Callable[[str], None]
) -> User:
    user, _customer = await make_customer(email="staff-analytics@example.com")
    set_staff_emails("staff-analytics@example.com")
    return user


# ===========================================================================
# Detection scorecard
# ===========================================================================


async def test_detection_scorecard_matches_family(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    _u, customer = await make_customer(email="detcust@example.com")

    injected_at = datetime.now(UTC) - timedelta(minutes=5)
    db.add(
        SimInjection(
            customer_id=customer.id,
            injected_type="job_change",
            injected_by=staff.email,
            params={"growth_factor": 1.4},
            injected_at=injected_at,
        )
    )
    db.add(
        LifeEvent(
            customer_id=customer.id,
            type=LifeEventType.JOB_CHANGE,
            confidence=0.82,
            evidence={"rule": "salary_change"},
            detected_at=injected_at + timedelta(seconds=45),
            status=LifeEventStatus.DETECTED,
        )
    )
    await db.commit()

    resp = await client.get(
        "/api/v1/console/analytics/detection", cookies=auth_cookies(staff)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"] == {
        "injected": 1,
        "detected": 1,
        "matched": 1,
        "detections_with_no_injection": 0,
    }
    row = body["rows"][0]
    assert row["injected_type"] == "job_change"
    assert row["detected"] is True
    assert row["detected_type"] == "job_change"
    assert row["matched"] is True
    assert row["confidence"] == 0.82
    assert 44 <= row["lag_seconds"] <= 46
    assert set(row["expected_types"]) == {"job_change", "salary_hike"}
    assert row["customer_name"] == customer.full_name


async def test_detection_scorecard_no_detection(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    _u, customer = await make_customer(email="detcust2@example.com")
    db.add(
        SimInjection(
            customer_id=customer.id,
            injected_type="home_purchase_intent",
            injected_by=staff.email,
            params={},
            injected_at=datetime.now(UTC) - timedelta(minutes=2),
        )
    )
    await db.commit()

    resp = await client.get(
        "/api/v1/console/analytics/detection", cookies=auth_cookies(staff)
    )
    body = resp.json()
    assert body["summary"]["injected"] == 1
    assert body["summary"]["detected"] == 0
    assert body["summary"]["matched"] == 0
    row = body["rows"][0]
    assert row["detected"] is False
    assert row["detected_type"] is None
    assert row["lag_seconds"] is None
    assert row["matched"] is False


async def test_detection_churn_none_expected_matches_when_silent(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    """churn_risk expects NO life event; silence is the correct (matched) outcome."""
    staff = await _staff(make_customer, set_staff_emails)
    _u, customer = await make_customer(email="churncust@example.com")
    db.add(
        SimInjection(
            customer_id=customer.id,
            injected_type="churn_risk",
            injected_by=staff.email,
            params={},
            injected_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    await db.commit()

    resp = await client.get(
        "/api/v1/console/analytics/detection", cookies=auth_cookies(staff)
    )
    row = resp.json()["rows"][0]
    assert row["expected_types"] == []
    assert row["detected"] is False
    assert row["matched"] is True  # correctly stayed silent
    assert resp.json()["summary"]["matched"] == 1


async def test_detection_counts_unprompted_detection(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    """A life event for a customer with no injection is a detection-with-no-injection."""
    staff = await _staff(make_customer, set_staff_emails)
    _u, customer = await make_customer(email="unprompted@example.com")
    db.add(
        LifeEvent(
            customer_id=customer.id,
            type=LifeEventType.TRAVEL,
            confidence=0.5,
            evidence={},
            detected_at=datetime.now(UTC),
            status=LifeEventStatus.DETECTED,
        )
    )
    await db.commit()

    resp = await client.get(
        "/api/v1/console/analytics/detection", cookies=auth_cookies(staff)
    )
    body = resp.json()
    assert body["summary"]["injected"] == 0
    assert body["summary"]["detections_with_no_injection"] == 1
    assert body["rows"] == []


async def test_detection_empty_state(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    resp = await client.get(
        "/api/v1/console/analytics/detection", cookies=auth_cookies(staff)
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "summary": {
            "injected": 0,
            "detected": 0,
            "matched": 0,
            "detections_with_no_injection": 0,
        },
        "rows": [],
    }


async def test_detection_requires_staff(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    user, _c = await make_customer(email="notstaff@example.com")
    set_staff_emails("someone-else@example.com")
    resp = await client.get(
        "/api/v1/console/analytics/detection", cookies=auth_cookies(user)
    )
    assert resp.status_code == 403


# ===========================================================================
# Funnel time series
# ===========================================================================


async def test_timeseries_buckets_today(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    _u, customer = await make_customer(email="tscust@example.com")

    now = datetime.now(UTC)
    db.add(
        AgentRun(
            agent="supervisor",
            trigger=AgentTriggerType.EVENT,
            status=AgentRunStatus.COMPLETED,
            customer_id=customer.id,
            started_at=now,
        )
    )
    db.add(
        Proposal(
            customer_id=customer.id,
            agent="engagement",
            kind=ProposalKind.NUDGE,
            title="t",
            body="b",
            action={"kind": "send_nudge"},
            status=ProposalStatus.EXECUTED,
            created_at=now,
            decided_at=now,
        )
    )
    db.add(
        Nudge(
            customer_id=customer.id,
            title="n",
            body="b",
            status=NudgeStatus.ACTED,
            created_at=now,
        )
    )
    db.add(
        LlmCall(
            provider="openai",
            model="gpt-4.1-mini",
            tier=LlmTier.FAST,
            tokens_in=100,
            tokens_out=50,
            cost_usd=Decimal("0.001234"),
            purpose="supervisor:classify",
            created_at=now,
        )
    )
    await db.commit()

    resp = await client.get(
        "/api/v1/console/analytics/timeseries",
        params={"days": 7},
        cookies=auth_cookies(staff),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["days"] == 7
    assert len(body["points"]) == 7
    today = body["points"][-1]
    assert today["date"] == now.date().isoformat()
    assert today["agent_runs"] == 1
    assert today["proposals_created"] == 1
    assert today["proposals_approved"] == 1
    assert today["nudges_sent"] == 1
    assert today["nudges_acted"] == 1
    assert Decimal(today["llm_cost_usd"]) == Decimal("0.001234")


async def test_timeseries_dense_zero_fill(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    resp = await client.get(
        "/api/v1/console/analytics/timeseries",
        params={"days": 5},
        cookies=auth_cookies(staff),
    )
    body = resp.json()
    assert len(body["points"]) == 5
    for point in body["points"]:
        assert point["agent_runs"] == 0
        assert point["proposals_created"] == 0
        assert Decimal(point["llm_cost_usd"]) == Decimal("0")
    # Dates are ascending and end today.
    dates = [p["date"] for p in body["points"]]
    assert dates == sorted(dates)
    assert dates[-1] == datetime.now(UTC).date().isoformat()


async def test_timeseries_rejects_out_of_range_days(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    resp = await client.get(
        "/api/v1/console/analytics/timeseries",
        params={"days": 999},
        cookies=auth_cookies(staff),
    )
    assert resp.status_code == 422


# ===========================================================================
# Proposal outcomes
# ===========================================================================


async def test_proposal_outcomes(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    _u, customer = await make_customer(email="propout@example.com")

    now = datetime.now(UTC)

    def _proposal(agent: str, status: ProposalStatus, decided: bool) -> Proposal:
        return Proposal(
            customer_id=customer.id,
            agent=agent,
            kind=ProposalKind.NUDGE,
            title="t",
            body="b",
            action={"kind": "send_nudge"},
            status=status,
            created_at=now,
            decided_at=(now + timedelta(seconds=20)) if decided else None,
        )

    db.add_all(
        [
            _proposal("engagement", ProposalStatus.EXECUTED, decided=True),
            _proposal("engagement", ProposalStatus.REJECTED, decided=True),
            _proposal("engagement", ProposalStatus.PENDING, decided=False),
            _proposal("adoption", ProposalStatus.APPROVED, decided=True),
        ]
    )
    await db.commit()

    resp = await client.get(
        "/api/v1/console/analytics/proposals", cookies=auth_cookies(staff)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["executed"] == 1
    assert body["rejected"] == 1
    assert body["pending"] == 1
    assert body["approved"] == 1
    # 3 decided proposals, each 20s after creation.
    assert body["avg_decision_seconds"] == 20.0

    by_agent = {row["agent"]: row for row in body["by_agent"]}
    assert by_agent["engagement"]["created"] == 3
    # approved counts EXECUTED + APPROVED together.
    assert by_agent["engagement"]["approved"] == 1
    assert by_agent["engagement"]["rejected"] == 1
    assert by_agent["adoption"]["approved"] == 1


async def test_proposal_outcomes_empty(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    resp = await client.get(
        "/api/v1/console/analytics/proposals", cookies=auth_cookies(staff)
    )
    body = resp.json()
    assert body["pending"] == 0
    assert body["avg_decision_seconds"] is None
    assert body["by_agent"] == []


# ===========================================================================
# Health budget fields
# ===========================================================================


async def test_health_reports_budget_fields(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    db.add(
        LlmCall(
            provider="openai",
            model="gpt-4.1",
            tier=LlmTier.SMART,
            tokens_in=10,
            tokens_out=10,
            cost_usd=Decimal("0.30"),
            purpose="supervisor:classify",
            created_at=datetime.now(UTC),
        )
    )
    await db.commit()

    resp = await client.get("/api/v1/console/health", cookies=auth_cookies(staff))
    assert resp.status_code == 200
    budget = resp.json()["llm_budget"]
    assert Decimal(budget["cost_usd_today"]) == Decimal("0.30")
    assert Decimal(budget["budget_usd"]) == Decimal("0.25")
    assert budget["over_budget"] is True


# ===========================================================================
# Inject-event ground-truth persistence
# ===========================================================================


async def test_inject_event_persists_ground_truth(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    from app.sim import personas as sim_personas

    staff = await _staff(make_customer, set_staff_emails)
    _u, customer = await make_customer(email="gtcust@example.com")

    persona = sim_personas.make_cohort(1, seed=11)[0]
    customer.persona = persona.model_dump(mode="json")
    db.add(
        Account(
            customer_id=customer.id,
            type=AccountType.SAVINGS,
            balance_paise=500_000_00,
            status=AccountStatus.ACTIVE,
        )
    )
    await db.commit()

    await get_redis().xlen(TXN_EVENTS)  # touch stream (created lazily)
    resp = await client.post(
        "/api/v1/console/sim/inject-event",
        json={"customer_id": str(customer.id), "type": "bonus_windfall"},
        cookies=auth_cookies(staff),
    )
    assert resp.status_code == 200

    rows = (
        (await db.execute(_select_injections(customer.id))).scalars().all()
    )
    assert len(rows) == 1
    injection = rows[0]
    assert injection.injected_type == "bonus_windfall"
    assert injection.injected_by == staff.email
    assert injection.params  # the script's ground-truth params were persisted


def _select_injections(customer_id: uuid.UUID) -> Any:
    import sqlalchemy as sa

    return sa.select(SimInjection).where(SimInjection.customer_id == customer_id)
