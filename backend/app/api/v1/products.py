"""Customer-facing product browse + self-service apply (auth required).

``GET /me/products`` lists the full catalog with per-customer eligibility and
holding status - a hard, code-only compliance filter (:mod:`app.services.products`).
For eligible, not-yet-held products, the personalized "why for you" reason
comes from the same LLM ranking chat uses (:func:`products.rank_products_llm_only`),
but a page view must never cost a fresh call: the ranking is cached in Redis,
keyed by customer id + a hash of the profile fields (+ holdings) that could
change the ranking, for 24h. A repeat view with an unchanged profile is a cache
hit (free); a genuinely changed profile (new holding, income update, meaningful
balance shift) is a cache miss (one fast-tier call). If the LLM has no key or
fails, the page still renders correctly - eligibility/held stay code-derived,
only the personalized reason is absent (cached briefly so a transient failure
doesn't retry on every request either).

``POST /me/products/{code}/apply`` creates a real HITL proposal (never a direct
holding - an RM reviews it, same as every other impactful action in this app)
plus a customer notification, guarding against duplicate requests.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Annotated

import orjson
from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.actions import create_proposal
from app.core.db import get_db
from app.core.logging import get_logger
from app.core.ratelimit import rate_limit
from app.core.redis import get_redis
from app.core.security import get_current_user
from app.llm.router import LLMRouter, get_router
from app.models.customer import Customer
from app.models.engagement import Proposal
from app.models.enums import DigitalMaturity, NotificationKind, ProposalKind, ProposalStatus
from app.models.identity import User
from app.schemas.products import ProductApplyResponse, ProductBrowseItem, ProductsBrowseResponse
from app.services import ledger, products
from app.services.notifications import notify

from .customers import _customer_for_user_or_404

router = APIRouter(prefix="/me/products", tags=["products"])

logger = get_logger(__name__)

_RANK_CACHE_PREFIX = "products:rank"
_RANK_CACHE_TTL_SECONDS = 24 * 60 * 60
"""A hit is free; a genuinely changed profile (income, holdings, life stage)
naturally busts the key (see :func:`_cache_key`), so 24h is just an upper bound
on how long a *stale-but-still-accurate* ranking survives."""
_RANK_CACHE_NEGATIVE_TTL_SECONDS = 5 * 60
"""Short TTL for "the LLM produced nothing usable" so a transient outage
doesn't retry on every page view, but a real fix recovers within minutes."""
_IDLE_BALANCE_BUCKET_PAISE = 50_000 * 100
"""Bucket granularity for the cache key's idle-balance component (matches the
FD-gap threshold in :mod:`app.services.products`). Ledger balances shift with
every transaction; without bucketing, an active account would bust the cache
(and cost an LLM call) on nearly every view even though the *recommendation*
hasn't meaningfully changed."""

_DIGITAL_MATURITY_SCORE: dict[DigitalMaturity, float] = {
    DigitalMaturity.LOW: 0.2,
    DigitalMaturity.MEDIUM: 0.5,
    DigitalMaturity.HIGH: 0.8,
}


def _build_profile(
    customer: Customer, *, held: list[str], idle_balance_paise: int
) -> products.CustomerProfile:
    """Assemble the ranking/eligibility profile from a customer's own record.

    ``age``/``dependents``/``risk_appetite`` live in the free-form ``persona``
    JSON (populated for sim-seeded customers and onboarding); real accounts
    without them simply rank/gate on the fields that are set.
    """
    persona = customer.persona or {}
    age = persona.get("age")
    dependents = persona.get("dependents")
    risk = persona.get("risk_appetite") or persona.get("risk")
    return products.CustomerProfile(
        annual_income_paise=customer.annual_income_paise,
        age=int(age) if isinstance(age, int | float) else None,
        segment=customer.segment,
        dependents=int(dependents) if isinstance(dependents, int | float) else 0,
        held_product_codes=held,
        idle_balance_paise=idle_balance_paise,
        risk_appetite=risk if isinstance(risk, str) and risk.strip() else None,
        digital_maturity=_DIGITAL_MATURITY_SCORE.get(customer.digital_maturity),
    )


def _cache_key(customer_id: uuid.UUID, profile: products.CustomerProfile) -> str:
    idle = profile.idle_balance_paise
    idle_bucket = idle // _IDLE_BALANCE_BUCKET_PAISE if idle is not None else None
    payload = {
        "income": profile.annual_income_paise,
        "age": profile.age,
        "segment": profile.segment,
        "dependents": profile.dependents,
        "idle_bucket": idle_bucket,
        "risk": profile.risk_appetite,
        "digital_maturity": profile.digital_maturity,
        "held": sorted(profile.held_product_codes),
    }
    digest = hashlib.sha256(orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)).hexdigest()[:24]
    return f"{_RANK_CACHE_PREFIX}:{customer_id}:{digest}"


async def _ranked_reasons(
    *,
    router: LLMRouter,
    customer_id: uuid.UUID,
    profile: products.CustomerProfile,
    eligible_not_held: list[str],
) -> dict[str, str]:
    """"Why for you" reasons for eligible, not-held products, Redis-cached.

    Returns ``{code: reason}`` for whichever codes the LLM actually reasoned
    about; a code missing from the map (cache miss with LLM failure, or the
    model simply not covering it) has no personalized reason - the caller
    treats that as "not available yet", never a 500.
    """
    if not eligible_not_held:
        return {}

    redis = get_redis()
    key = _cache_key(customer_id, profile)
    cached = await redis.get(key)
    if cached is not None:
        try:
            items = orjson.loads(cached)
        except orjson.JSONDecodeError:
            items = []
        return {item["code"]: item["reason"] for item in items if item.get("reason")}

    ranked = await products.rank_products_llm_only(
        profile, router=router, limit=len(eligible_not_held)
    )
    if ranked is None:
        await redis.set(key, orjson.dumps([]).decode(), ex=_RANK_CACHE_NEGATIVE_TTL_SECONDS)
        return {}

    reasons = {c.code: "; ".join(c.reasons) for c in ranked if c.reasons}
    cache_value = [{"code": code, "reason": reason} for code, reason in reasons.items()]
    await redis.set(key, orjson.dumps(cache_value).decode(), ex=_RANK_CACHE_TTL_SECONDS)
    return reasons


@router.get("", response_model=ProductsBrowseResponse)
async def browse_products(
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ProductsBrowseResponse:
    customer = await _customer_for_user_or_404(db, user)
    held = await products.held_product_codes(db, customer.id)
    held_set = set(held)
    pending_set = await _pending_product_codes(db, customer.id)
    idle_balance = await ledger.get_customer_balance(db, customer.id)
    profile = _build_profile(customer, held=held, idle_balance_paise=idle_balance)

    entries = products.catalog_with_eligibility(profile)
    eligible_not_held = [e.code for e in entries if e.eligible and e.code not in held_set]

    reasons: dict[str, str] = {}
    if eligible_not_held:
        try:
            reasons = await _ranked_reasons(
                router=get_router(),
                customer_id=customer.id,
                profile=profile,
                eligible_not_held=eligible_not_held,
            )
        except Exception as exc:
            # Redis (or an unexpected router) hiccup - degrade to "no reasons",
            # never fail the whole page over a personalization nicety.
            logger.warning("products_rank_cache_failed", error=str(exc))

    items = [
        ProductBrowseItem(
            code=e.code,
            name=e.name,
            category=e.category,
            description=e.description,
            eligible=e.eligible,
            held=e.code in held_set,
            pending=e.code in pending_set,
            reason=(
                None
                if e.code in held_set
                else (reasons.get(e.code) if e.eligible else e.ineligibility_reason)
            ),
        )
        for e in entries
    ]
    return ProductsBrowseResponse(products=items)


async def _pending_product_codes(db: AsyncSession, customer_id: uuid.UUID) -> set[str]:
    """Product codes with a PENDING self-service (or agent) offer proposal.

    Lets the browse page show "Requested" on reload without client-only state -
    it mirrors the exact guard :func:`apply_for_product` uses to reject a
    duplicate request.
    """
    actions = (
        await db.scalars(
            select(Proposal.action).where(
                Proposal.customer_id == customer_id,
                Proposal.kind == ProposalKind.PRODUCT_OFFER,
                Proposal.status == ProposalStatus.PENDING,
            )
        )
    ).all()
    return {
        str(action["product_code"])
        for action in actions
        if isinstance(action, dict) and action.get("product_code")
    }


_PRODUCT_CODE_PATTERN = r"^[a-z0-9_]{1,64}$"
"""Catalog codes are lowercase snake identifiers (see `app.services.products.CATALOG`);
constraining the path param rejects junk before any DB lookup."""


@router.post(
    "/{code}/apply",
    response_model=ProductApplyResponse,
    # Creates a real HITL proposal + a notification. 10/hour per user stops a client
    # from spamming the review queue while leaving room for genuine multi-product apps.
    dependencies=[
        Depends(rate_limit("product_apply", limit=40, window_seconds=3600, key="by_user"))
    ],
)
async def apply_for_product(
    code: Annotated[str, Path(pattern=_PRODUCT_CODE_PATTERN)],
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ProductApplyResponse:
    customer = await _customer_for_user_or_404(db, user)
    product = await products.get_product(db, code)
    if product is None:
        raise HTTPException(status_code=404, detail="Unknown product")

    held = await products.held_product_codes(db, customer.id)
    if code in held:
        raise HTTPException(status_code=409, detail="You already hold this product")

    pending = await db.scalar(
        select(Proposal.id).where(
            Proposal.customer_id == customer.id,
            Proposal.kind == ProposalKind.PRODUCT_OFFER,
            Proposal.status == ProposalStatus.PENDING,
            Proposal.action["product_code"].astext == code,
        )
    )
    if pending is not None:
        raise HTTPException(
            status_code=409, detail="A request for this product is already pending review"
        )

    idle_balance = await ledger.get_customer_balance(db, customer.id)
    profile = _build_profile(customer, held=held, idle_balance_paise=idle_balance)
    if not products.is_eligible(code, profile):
        raise HTTPException(status_code=403, detail="Not eligible for this product yet")

    proposal = await create_proposal(
        db,
        customer_id=customer.id,
        agent="self_service",
        kind=ProposalKind.PRODUCT_OFFER,
        title=f"Customer requested {product.name}",
        body=f"{customer.full_name} requested {product.name} from the products page.",
        action={"kind": "product_offer", "product_code": code},
    )
    await notify(
        db,
        customer.id,
        NotificationKind.OFFER,
        "We received your request",
        f"We've received your request for {product.name}. "
        "A relationship manager will review it shortly.",
        link="/app/products",
    )
    return ProductApplyResponse(proposal_id=proposal.id, status="pending_approval")
