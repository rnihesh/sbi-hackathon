"""Products browse + self-service apply: eligibility/held merge, LLM-ranking
cache (hit/miss/failure), and the apply -> HITL proposal + notification flow.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Holding, Product
from app.models.engagement import Notification, Proposal
from app.models.enums import DigitalMaturity, HoldingStatus, NotificationKind, ProposalStatus
from app.services.products import seed_catalog
from tests.agents.conftest import FakeRouter, ScriptedHandler, make_response

from .conftest import auth_cookies

pytestmark = pytest.mark.anyio

_PROFILE = {
    "annual_income_paise": 800_000 * 100,
    "segment": "salaried",
    "persona": {"age": 35, "dependents": 2, "risk_appetite": "medium"},
    "digital_maturity": DigitalMaturity.MEDIUM,
}


def _rank_router(ranked: dict[str, Any]) -> FakeRouter:
    import orjson

    handler = ScriptedHandler(
        queues={"match_products": [make_response(orjson.dumps(ranked).decode())]},
    )
    return FakeRouter(handler)


def _boom_router() -> FakeRouter:
    def _raise(**_: Any) -> Any:
        raise RuntimeError("provider down")

    return FakeRouter(_raise)


async def _hold(db: AsyncSession, customer_id: uuid.UUID, code: str) -> None:
    product = await db.scalar(sa.select(Product).where(Product.code == code))
    assert product is not None
    db.add(Holding(customer_id=customer_id, product_id=product.id, status=HoldingStatus.ACTIVE))
    await db.commit()


async def test_browse_requires_auth(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/me/products")
    assert resp.status_code == 401


async def test_apply_requires_auth(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/me/products/term_insurance/apply")
    assert resp.status_code == 401


async def test_browse_merges_eligibility_held_and_llm_reasons(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.products as products_module

    await seed_catalog(db)
    await db.commit()
    user, customer = await make_customer(**_PROFILE)
    await _hold(db, customer.id, "savings_account")

    router = _rank_router(
        {
            "ranked": [
                {
                    "code": "term_insurance",
                    "score": 0.9,
                    "reasons": ["2 dependents, no cover on file"],
                },
                {
                    "code": "mutual_fund_sip",
                    "score": 0.7,
                    "reasons": ["income supports a SIP", "risk appetite is medium"],
                },
            ]
        }
    )
    monkeypatch.setattr(products_module, "get_router", lambda: router)

    resp = await client.get("/api/v1/me/products", cookies=auth_cookies(user))
    assert resp.status_code == 200
    body = resp.json()
    by_code = {p["code"]: p for p in body["products"]}
    assert len(by_code) == 15  # full catalog, not just eligible

    # Held: reason always null, regardless of ranking.
    assert by_code["savings_account"]["held"] is True
    assert by_code["savings_account"]["eligible"] is True
    assert by_code["savings_account"]["reason"] is None
    assert by_code["savings_account"]["pending"] is False
    assert by_code["term_insurance"]["pending"] is False

    # Ineligible: rule-grounded reason, no LLM involvement.
    assert by_code["zero_balance_account"]["eligible"] is False
    assert by_code["zero_balance_account"]["held"] is False
    assert "300,000" in by_code["zero_balance_account"]["reason"]
    assert by_code["current_account"]["reason"] == "Only for business customers"
    assert by_code["senior_citizen_scheme"]["reason"] == "Available from age 60"
    assert by_code["pension_account"]["reason"] == "Available from age 55"

    # Eligible + not held: LLM reason when the model covered the code...
    assert by_code["term_insurance"]["eligible"] is True
    assert by_code["term_insurance"]["reason"] == "2 dependents, no cover on file"
    assert by_code["mutual_fund_sip"]["reason"] == "income supports a SIP; risk appetite is medium"
    # ...null (not fabricated) when the model didn't.
    assert by_code["salary_account"]["eligible"] is True
    assert by_code["salary_account"]["reason"] is None
    assert by_code["fixed_deposit"]["reason"] is None

    call = router.calls[0]
    assert call["tier"] == "fast"
    assert call["json_mode"] is True
    assert call["purpose"] == "match_products"

    # Repeat view: same profile/holdings -> cache hit, zero further LLM calls.
    resp2 = await client.get("/api/v1/me/products", cookies=auth_cookies(user))
    assert resp2.status_code == 200
    assert resp2.json() == body
    assert len(router.calls) == 1


async def test_browse_degrades_gracefully_on_llm_failure(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.products as products_module

    await seed_catalog(db)
    await db.commit()
    user, _customer = await make_customer(**_PROFILE)

    router = _boom_router()
    monkeypatch.setattr(products_module, "get_router", lambda: router)

    resp = await client.get("/api/v1/me/products", cookies=auth_cookies(user))
    assert resp.status_code == 200
    by_code = {p["code"]: p for p in resp.json()["products"]}
    # Eligibility/held still correct...
    assert by_code["term_insurance"]["eligible"] is True
    assert by_code["senior_citizen_scheme"]["eligible"] is False
    assert by_code["senior_citizen_scheme"]["reason"] == "Available from age 60"
    # ...but no personalized reason was fabricated.
    assert by_code["term_insurance"]["reason"] is None
    assert by_code["mutual_fund_sip"]["reason"] is None
    assert len(router.calls) == 1

    # A short negative cache means a second view doesn't hammer the provider.
    resp2 = await client.get("/api/v1/me/products", cookies=auth_cookies(user))
    assert resp2.status_code == 200
    assert len(router.calls) == 1


async def test_apply_creates_proposal_and_notification(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Any
) -> None:
    await seed_catalog(db)
    await db.commit()
    user, customer = await make_customer(**_PROFILE)

    resp = await client.post(
        "/api/v1/me/products/term_insurance/apply", cookies=auth_cookies(user)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending_approval"
    proposal_id = uuid.UUID(body["proposal_id"])

    proposal = await db.get(Proposal, proposal_id)
    assert proposal is not None
    assert proposal.customer_id == customer.id
    assert proposal.agent == "self_service"
    assert proposal.status == ProposalStatus.PENDING
    assert proposal.action == {"kind": "product_offer", "product_code": "term_insurance"}
    assert "term_insurance" not in proposal.title.lower()  # uses the product name, not the code
    assert "SBI Life Term Insurance" in proposal.title

    notif = await db.scalar(
        sa.select(Notification).where(Notification.customer_id == customer.id)
    )
    assert notif is not None
    assert notif.kind == NotificationKind.OFFER


async def test_apply_conflict_when_already_held(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Any
) -> None:
    await seed_catalog(db)
    await db.commit()
    user, customer = await make_customer(**_PROFILE)
    await _hold(db, customer.id, "savings_account")

    resp = await client.post(
        "/api/v1/me/products/savings_account/apply", cookies=auth_cookies(user)
    )
    assert resp.status_code == 409


async def test_apply_conflict_when_already_pending(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Any
) -> None:
    await seed_catalog(db)
    await db.commit()
    user, _customer = await make_customer(**_PROFILE)

    first = await client.post(
        "/api/v1/me/products/term_insurance/apply", cookies=auth_cookies(user)
    )
    assert first.status_code == 200

    second = await client.post(
        "/api/v1/me/products/term_insurance/apply", cookies=auth_cookies(user)
    )
    assert second.status_code == 409


async def test_browse_reflects_pending_after_apply(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Any
) -> None:
    """A pending request survives a reload without client-only state - the
    browse page's own ``pending`` flag mirrors the same DB row apply's 409
    guard checks."""
    await seed_catalog(db)
    await db.commit()
    user, _customer = await make_customer(**_PROFILE)

    before = await client.get("/api/v1/me/products", cookies=auth_cookies(user))
    by_code_before = {p["code"]: p for p in before.json()["products"]}
    assert by_code_before["term_insurance"]["pending"] is False

    applied = await client.post(
        "/api/v1/me/products/term_insurance/apply", cookies=auth_cookies(user)
    )
    assert applied.status_code == 200

    after = await client.get("/api/v1/me/products", cookies=auth_cookies(user))
    by_code_after = {p["code"]: p for p in after.json()["products"]}
    assert by_code_after["term_insurance"]["pending"] is True
    assert by_code_after["term_insurance"]["held"] is False


async def test_apply_forbidden_when_ineligible(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Any
) -> None:
    await seed_catalog(db)
    await db.commit()
    user, _customer = await make_customer(**_PROFILE)  # age 35, not 60+

    resp = await client.post(
        "/api/v1/me/products/senior_citizen_scheme/apply", cookies=auth_cookies(user)
    )
    assert resp.status_code == 403


async def test_apply_unknown_product_404(
    client: httpx.AsyncClient, db: AsyncSession, make_customer: Any
) -> None:
    await seed_catalog(db)
    await db.commit()
    user, _customer = await make_customer(**_PROFILE)

    resp = await client.post(
        "/api/v1/me/products/not_a_real_code/apply", cookies=auth_cookies(user)
    )
    assert resp.status_code == 404
