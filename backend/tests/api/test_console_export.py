"""Console CSV exports: ``GET /console/export/leads.csv`` and
``/console/export/detection.csv``.

Both reuse the exact query/grading logic backing their JSON counterparts (see
``app.api.v1.console._fetch_leads`` / ``_compute_detection``) - these tests cover the
export-specific concerns: staff gate, ``text/csv`` content-type, a real header row,
and safe quoting of a value containing a comma and a quote (via the stdlib ``csv``
module, not hand-rolled joining).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm import Lead
from app.models.enums import LeadStage, LifeEventStatus, LifeEventType
from app.models.sim_injection import SimInjection
from tests.api.conftest import auth_cookies


async def _staff(
    make_customer: Callable[..., Any], set_staff_emails: Callable[[str], None]
) -> Any:
    user, _customer = await make_customer(email="staff-export@example.com")
    set_staff_emails("staff-export@example.com")
    return user


# ===========================================================================
# leads.csv
# ===========================================================================


async def test_export_leads_csv_requires_staff(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    user, _customer = await make_customer(email="regular-export@example.com")
    set_staff_emails("someone-else@example.com")
    resp = await client.get("/api/v1/console/export/leads.csv", cookies=auth_cookies(user))
    assert resp.status_code == 403


async def test_export_leads_csv_content_type_and_headers(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    _u, customer = await make_customer(email="leadexport@example.com")
    db.add(
        Lead(
            customer_id=customer.id, source="chat", name="Plain Name",
            intent_score=0.5, stage=LeadStage.NEW,
        )
    )
    await db.commit()

    resp = await client.get("/api/v1/console/export/leads.csv", cookies=auth_cookies(staff))
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert resp.headers["content-disposition"] == "attachment; filename=leads.csv"

    rows = list(csv.reader(io.StringIO(resp.text)))
    assert rows[0] == [
        "id", "customer_id", "customer_name", "source", "name", "email",
        "phone", "intent_score", "stage", "created_at",
    ]
    assert len(rows) == 2  # header + one lead
    assert rows[1][4] == "Plain Name"
    assert rows[1][8] == "new"


async def test_export_leads_csv_quotes_comma_and_quote_in_name(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    _u, customer = await make_customer(email="leadquote@example.com")
    tricky_name = 'Rao, "Big" Traders'
    db.add(
        Lead(
            customer_id=customer.id, source="chat", name=tricky_name,
            intent_score=0.1, stage=LeadStage.NEW,
        )
    )
    await db.commit()

    resp = await client.get("/api/v1/console/export/leads.csv", cookies=auth_cookies(staff))
    assert resp.status_code == 200

    # The raw body must not naively contain an unescaped comma splitting the field -
    # round-tripping through csv.reader is the real assertion (proves proper quoting).
    rows = list(csv.reader(io.StringIO(resp.text)))
    name_col = rows[0].index("name")
    assert rows[1][name_col] == tricky_name


async def test_export_leads_csv_no_leads_is_header_only(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    resp = await client.get("/api/v1/console/export/leads.csv", cookies=auth_cookies(staff))
    assert resp.status_code == 200
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert len(rows) == 1


# ===========================================================================
# detection.csv
# ===========================================================================


async def test_export_detection_csv_requires_staff(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    user, _customer = await make_customer(email="regular-export2@example.com")
    set_staff_emails("someone-else@example.com")
    resp = await client.get("/api/v1/console/export/detection.csv", cookies=auth_cookies(user))
    assert resp.status_code == 403


async def test_export_detection_csv_content_type_and_headers(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    _u, customer = await make_customer(email="detectexport@example.com")
    db.add(
        SimInjection(
            customer_id=customer.id, injected_type="home_purchase_intent", injected_by="test"
        )
    )
    await db.flush()
    from app.models.engagement import LifeEvent

    db.add(
        LifeEvent(
            customer_id=customer.id,
            type=LifeEventType.HOME_INTENT,
            confidence=0.9,
            status=LifeEventStatus.DETECTED,
        )
    )
    await db.commit()

    resp = await client.get("/api/v1/console/export/detection.csv", cookies=auth_cookies(staff))
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert resp.headers["content-disposition"] == "attachment; filename=detection.csv"

    rows = list(csv.reader(io.StringIO(resp.text)))
    assert rows[0] == [
        "injection_id", "customer_id", "customer_name", "injected_type", "injected_at",
        "expected_types", "detected", "detected_type", "confidence", "lag_seconds", "matched",
    ]
    assert len(rows) == 2
    assert rows[1][3] == "home_purchase_intent"
    assert rows[1][6] == "True"
    assert rows[1][7] == "home_intent"
    assert rows[1][10] == "True"


async def test_export_detection_csv_matches_json_endpoint_row_count(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    """Same underlying grading pass as the JSON endpoint - not a second, divergent
    implementation."""
    staff = await _staff(make_customer, set_staff_emails)
    _u, customer = await make_customer(email="detectexport2@example.com")
    db.add(
        SimInjection(
            customer_id=customer.id, injected_type="bonus_windfall", injected_by="test"
        )
    )
    await db.commit()

    csv_resp = await client.get(
        "/api/v1/console/export/detection.csv", cookies=auth_cookies(staff)
    )
    json_resp = await client.get(
        "/api/v1/console/analytics/detection", cookies=auth_cookies(staff)
    )
    csv_rows = list(csv.reader(io.StringIO(csv_resp.text)))
    assert len(csv_rows) - 1 == len(json_resp.json()["rows"])
