"""Product catalog + deterministic eligibility matching.

The **rules** here decide eligibility and surface product-gap reasons; the LLM
(in the adoption/engagement agents) only writes the final pitch. This split is
deliberate: suitability and eligibility must be auditable and reproducible, so
they live in code, not in a prompt.

Money fields are paise (integer). ``annual_income_paise`` etc.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Holding, Product
from app.models.enums import HoldingStatus

_RUPEE = 100  # paise per rupee

# ---------------------------------------------------------------------------
# Canonical catalog. ``eligibility`` keys are read by :func:`match_products`.
#   min_income_paise / max_income_paise : annual income band
#   min_age / max_age                   : age band
#   segment                             : "salaried" | "business" | None
#   needs_risk_profile                  : requires a recorded risk answer
# ---------------------------------------------------------------------------
CATALOG: list[dict[str, Any]] = [
    {
        "code": "savings_account", "name": "SBI Savings Account", "category": "deposit",
        "description": "Everyday savings account with UPI, netbanking and debit card.",
        "eligibility": {"min_age": 10},
    },
    {
        "code": "zero_balance_account", "name": "SBI Basic (Zero-Balance) Account",
        "category": "deposit",
        "description": "No minimum balance account for students and first-time savers.",
        "eligibility": {"min_age": 10, "max_income_paise": 300_000 * _RUPEE},
    },
    {
        "code": "salary_account", "name": "SBI Salary Account", "category": "deposit",
        "description": "Zero-balance salary account with auto-sweep and perks.",
        "eligibility": {"min_age": 18, "segment": "salaried"},
    },
    {
        "code": "current_account", "name": "SBI Current Account", "category": "deposit",
        "description": "Business current account with high transaction limits.",
        "eligibility": {"min_age": 18, "segment": "business"},
    },
    {
        "code": "fixed_deposit", "name": "SBI Fixed Deposit", "category": "investment",
        "description": "Lock-in deposit at assured interest for idle balances.",
        "eligibility": {"min_age": 10},
    },
    {
        "code": "recurring_deposit", "name": "SBI Recurring Deposit", "category": "investment",
        "description": "Monthly savings deposit that builds a corpus over time.",
        "eligibility": {"min_age": 10},
    },
    {
        "code": "senior_citizen_scheme", "name": "SBI Senior Citizen Savings Scheme",
        "category": "investment",
        "description": "Higher-interest scheme for citizens aged 60+.",
        "eligibility": {"min_age": 60},
    },
    {
        "code": "pension_account", "name": "SBI Pension Account", "category": "deposit",
        "description": "Account tailored for pension credits and seniors.",
        "eligibility": {"min_age": 55},
    },
    {
        "code": "credit_card", "name": "SBI Credit Card", "category": "card",
        "description": "Rewards credit card with EMI and UPI-on-card.",
        "eligibility": {"min_age": 21, "min_income_paise": 300_000 * _RUPEE},
    },
    {
        "code": "mutual_fund_sip", "name": "SBI Mutual Fund SIP", "category": "investment",
        "description": "Systematic monthly investment across equity/debt funds.",
        "eligibility": {
            "min_age": 18, "min_income_paise": 500_000 * _RUPEE, "needs_risk_profile": True,
        },
    },
    {
        "code": "term_insurance", "name": "SBI Life Term Insurance", "category": "insurance",
        "description": "Pure protection life cover for dependents.",
        "eligibility": {"min_age": 18, "max_age": 60},
    },
    {
        "code": "personal_accident_cover", "name": "SBI Personal Accident Cover",
        "category": "insurance",
        "description": "Low-cost accidental death and disability cover.",
        "eligibility": {"min_age": 18},
    },
    {
        "code": "home_loan", "name": "SBI Home Loan", "category": "loan",
        "description": "Home purchase / construction loan at floating rates.",
        "eligibility": {"min_age": 21, "min_income_paise": 600_000 * _RUPEE},
    },
    {
        "code": "od_facility", "name": "SBI Overdraft Facility", "category": "loan",
        "description": "Working-capital overdraft against current account.",
        "eligibility": {"min_age": 21, "segment": "business"},
    },
    {
        "code": "gst_linked_account", "name": "SBI GST-Linked Business Account",
        "category": "deposit",
        "description": "Current account with GST reconciliation and reporting.",
        "eligibility": {"min_age": 21, "segment": "business"},
    },
]

_CATALOG_BY_CODE: dict[str, dict[str, Any]] = {p["code"]: p for p in CATALOG}


@dataclass(slots=True)
class CustomerProfile:
    """Inputs the matcher reasons over (all optional except what rules need)."""

    annual_income_paise: int | None = None
    age: int | None = None
    segment: str | None = None  # "salaried" | "business" | None
    dependents: int = 0
    held_product_codes: list[str] = field(default_factory=list)
    idle_balance_paise: int | None = None
    risk_appetite: str | None = None  # e.g. "low" | "medium" | "high"
    digital_maturity: float | None = None


@dataclass(slots=True)
class ProductCandidate:
    """A ranked product recommendation with human-readable reasons."""

    code: str
    name: str
    category: str
    score: float
    reasons: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "category": self.category,
            "score": round(self.score, 3),
            "reasons": self.reasons,
        }


# ---------------------------------------------------------------------------
# Catalog CRUD
# ---------------------------------------------------------------------------


async def seed_catalog(session: AsyncSession) -> int:
    """Idempotently upsert the canonical catalog. Returns rows touched."""
    count = 0
    for spec in CATALOG:
        stmt = (
            pg_insert(Product)
            .values(
                code=spec["code"],
                name=spec["name"],
                category=spec["category"],
                description=spec.get("description"),
                eligibility=spec.get("eligibility", {}),
            )
            .on_conflict_do_update(
                index_elements=[Product.code],
                set_={
                    "name": spec["name"],
                    "category": spec["category"],
                    "description": spec.get("description"),
                    "eligibility": spec.get("eligibility", {}),
                },
            )
        )
        await session.execute(stmt)
        count += 1
    await session.flush()
    return count


async def get_product(session: AsyncSession, code: str) -> Product | None:
    result: Product | None = await session.scalar(sa.select(Product).where(Product.code == code))
    return result


async def list_products(session: AsyncSession, category: str | None = None) -> list[Product]:
    stmt = sa.select(Product).order_by(Product.category, Product.name)
    if category is not None:
        stmt = stmt.where(Product.category == category)
    return list((await session.scalars(stmt)).all())


async def upsert_product(
    session: AsyncSession,
    *,
    code: str,
    name: str,
    category: str,
    description: str | None = None,
    eligibility: dict[str, Any] | None = None,
) -> Product:
    stmt = (
        pg_insert(Product)
        .values(
            code=code, name=name, category=category,
            description=description, eligibility=eligibility or {},
        )
        .on_conflict_do_update(
            index_elements=[Product.code],
            set_={
                "name": name, "category": category,
                "description": description, "eligibility": eligibility or {},
            },
        )
        .returning(Product)
    )
    product = (await session.execute(stmt)).scalar_one()
    await session.flush()
    return product


# ---------------------------------------------------------------------------
# Eligibility + matching (pure rules)
# ---------------------------------------------------------------------------


def _is_eligible(spec: dict[str, Any], profile: CustomerProfile) -> bool:
    elig = spec.get("eligibility", {})
    income, age = profile.annual_income_paise, profile.age

    min_inc = elig.get("min_income_paise")
    if min_inc is not None and (income is None or income < min_inc):
        return False
    max_inc = elig.get("max_income_paise")
    if max_inc is not None and income is not None and income > max_inc:
        return False
    min_age = elig.get("min_age")
    if min_age is not None and age is not None and age < min_age:
        return False
    max_age = elig.get("max_age")
    if max_age is not None and age is not None and age > max_age:
        return False
    seg = elig.get("segment")
    return not (seg is not None and profile.segment != seg)


def _score_and_reasons(
    spec: dict[str, Any], profile: CustomerProfile
) -> tuple[float, list[str]]:
    """Deterministic gap-based scoring. Higher = stronger recommendation."""
    code = spec["code"]
    category = spec["category"]
    score = 0.3  # base for any eligible product
    reasons: list[str] = []

    # Life-cover gap: dependents but no insurance.
    has_insurance = any(
        c in profile.held_product_codes
        for c in ("term_insurance", "personal_accident_cover")
    )
    if category == "insurance" and not has_insurance:
        if profile.dependents > 0:
            score += 0.5
            reasons.append(
                f"{profile.dependents} dependent(s) but no life/accident cover on file"
            )
        else:
            score += 0.2
            reasons.append("no protection cover held yet")

    # Idle-balance gap: sizeable idle balance but no FD.
    idle = profile.idle_balance_paise
    if code == "fixed_deposit" and idle is not None and idle > 50_000 * _RUPEE:
        score += 0.45
        reasons.append(
            f"~₹{idle // _RUPEE:,} sitting idle in savings — could earn FD interest"
        )
    if code == "recurring_deposit" and (profile.annual_income_paise or 0) > 0:
        score += 0.1
        reasons.append("a recurring deposit builds a disciplined savings habit")

    # Wealth gap: comfortable income but no market-linked investment.
    if code == "mutual_fund_sip":
        score += 0.35
        reasons.append("income supports a monthly SIP for long-term growth")
        if profile.risk_appetite:
            reasons.append(f"risk appetite recorded as '{profile.risk_appetite}'")

    # Convenience / credit-building gap.
    if code == "credit_card":
        score += 0.25
        reasons.append("eligible for a rewards credit card to build credit history")

    # Segment-native products.
    if spec.get("eligibility", {}).get("segment") == profile.segment and profile.segment:
        score += 0.2
        reasons.append(f"fits your {profile.segment} profile")

    # Senior-specific uplift.
    if code in ("senior_citizen_scheme", "pension_account") and (profile.age or 0) >= 60:
        score += 0.4
        reasons.append("senior-citizen benefits and higher interest apply")

    if not reasons:
        reasons.append(f"you are eligible for the {spec['name']}")
    return min(score, 1.0), reasons


def match_products(
    profile: CustomerProfile, *, limit: int = 5
) -> list[ProductCandidate]:
    """Rank eligible, not-yet-held products for a customer profile.

    Pure function over the in-memory :data:`CATALOG` (no DB) so it is trivially
    testable and reproducible. Candidates are sorted by score then code.
    """
    held = set(profile.held_product_codes)
    candidates: list[ProductCandidate] = []
    for spec in CATALOG:
        if spec["code"] in held:
            continue
        if not _is_eligible(spec, profile):
            continue
        score, reasons = _score_and_reasons(spec, profile)
        candidates.append(
            ProductCandidate(
                code=spec["code"],
                name=spec["name"],
                category=spec["category"],
                score=score,
                reasons=reasons,
            )
        )
    candidates.sort(key=lambda c: (-c.score, c.code))
    return candidates[:limit]


# ---------------------------------------------------------------------------
# Holdings
# ---------------------------------------------------------------------------


async def activate_holding(
    session: AsyncSession,
    *,
    customer_id: uuid.UUID,
    product_code: str,
    status: HoldingStatus = HoldingStatus.ACTIVE,
) -> Holding:
    """Create or update a customer's holding for ``product_code``."""
    product = await get_product(session, product_code)
    if product is None:
        raise ValueError(f"unknown product code: {product_code}")

    existing = await session.scalar(
        sa.select(Holding).where(
            Holding.customer_id == customer_id, Holding.product_id == product.id
        )
    )
    if existing is not None:
        existing.status = status
        await session.flush()
        return existing

    holding = Holding(customer_id=customer_id, product_id=product.id, status=status)
    session.add(holding)
    await session.flush()
    return holding


async def held_product_codes(session: AsyncSession, customer_id: uuid.UUID) -> list[str]:
    """Return the product codes a customer currently holds (any status)."""
    stmt = (
        sa.select(Product.code)
        .join(Holding, Holding.product_id == Product.id)
        .where(Holding.customer_id == customer_id)
    )
    return list((await session.scalars(stmt)).all())


def catalog_codes() -> list[str]:
    """All known product codes (for validation / prompts)."""
    return list(_CATALOG_BY_CODE.keys())
