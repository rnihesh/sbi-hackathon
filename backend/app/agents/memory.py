"""Agent memory: episodic recall + structured profile facts (pgvector-backed).

``remember`` embeds and stores a memory; ``recall`` does cosine top-k with a
recency decay (``score = cosine_sim * exp(-age_days/30)``) so fresh, relevant
memories win; ``profile_facts`` returns a structured snapshot the agents and the
policy suitability gate consume.

The embedder is injectable so tests can supply a deterministic fake (and seed
vectors directly) without hitting a provider.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.embeddings import Embedder, get_embedder
from app.models.catalog import Holding, Product
from app.models.customer import Customer
from app.models.enums import MemoryKind
from app.models.memory import AgentMemory

_DECAY_DAYS = 30.0
_RISK_WORDS = {
    "conservative": "low", "low risk": "low", "safe": "low",
    "moderate": "medium", "balanced": "medium",
    "aggressive": "high", "high risk": "high", "growth": "high",
}


def _coerce_kind(kind: MemoryKind | str) -> MemoryKind:
    return kind if isinstance(kind, MemoryKind) else MemoryKind(kind)


@dataclass(slots=True)
class MemoryHit:
    """A recalled memory with its similarity and recency-decayed score."""

    id: uuid.UUID
    text: str
    kind: str
    similarity: float
    age_days: float
    score: float
    created_at: datetime


async def remember(
    session: AsyncSession,
    customer_id: uuid.UUID,
    kind: MemoryKind | str,
    text: str,
    *,
    embedder: Embedder | None = None,
) -> AgentMemory:
    """Embed ``text`` and store it as a memory for ``customer_id``."""
    embedder = embedder or get_embedder()
    embedding: list[float] | None = None
    if embedder.available():
        embedding = await embedder.embed(text)
    row = AgentMemory(
        customer_id=customer_id,
        kind=_coerce_kind(kind),
        text=text,
        embedding=embedding,
    )
    session.add(row)
    await session.flush()
    return row


async def recall(
    session: AsyncSession,
    customer_id: uuid.UUID,
    query: str,
    k: int = 6,
    *,
    embedder: Embedder | None = None,
    candidate_multiplier: int = 4,
) -> list[MemoryHit]:
    """Return the top-``k`` memories for ``customer_id`` by similarity x recency.

    Fetches ``k * candidate_multiplier`` nearest neighbours by cosine distance
    (in the DB), then re-ranks in Python with the recency decay so recent
    memories are preferred among comparably-similar ones.
    """
    embedder = embedder or get_embedder()
    if not embedder.available():
        return []
    qvec = await embedder.embed(query)

    distance = AgentMemory.embedding.cosine_distance(qvec).label("distance")
    stmt = (
        sa.select(AgentMemory, distance)
        .where(
            AgentMemory.customer_id == customer_id,
            AgentMemory.embedding.is_not(None),
        )
        .order_by(distance)
        .limit(max(k * candidate_multiplier, k))
    )
    rows = (await session.execute(stmt)).all()

    now = datetime.now(UTC)
    hits: list[MemoryHit] = []
    for mem, dist in rows:
        similarity = 1.0 - float(dist)
        created = mem.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        age_days = max((now - created).total_seconds() / 86400.0, 0.0)
        score = similarity * math.exp(-age_days / _DECAY_DAYS)
        hits.append(
            MemoryHit(
                id=mem.id,
                text=mem.text,
                kind=mem.kind.value,
                similarity=round(similarity, 4),
                age_days=round(age_days, 2),
                score=round(score, 4),
                created_at=created,
            )
        )
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:k]


async def profile_facts(session: AsyncSession, customer_id: uuid.UUID) -> dict[str, object]:
    """Return a structured profile snapshot for a customer.

    Combines structured columns (name/income/city/…) with FACT and PREFERENCE
    memories, and derives ``income``/``risk`` keys for the suitability gate.
    """
    customer = await session.get(Customer, customer_id)
    if customer is None:
        return {"exists": False}

    fact_rows = list(
        (
            await session.scalars(
                sa.select(AgentMemory)
                .where(
                    AgentMemory.customer_id == customer_id,
                    AgentMemory.kind.in_([MemoryKind.FACT, MemoryKind.PREFERENCE]),
                )
                .order_by(AgentMemory.created_at.desc())
                .limit(20)
            )
        ).all()
    )
    facts = [r.text for r in fact_rows if r.kind is MemoryKind.FACT]
    preferences = [r.text for r in fact_rows if r.kind is MemoryKind.PREFERENCE]

    held = list(
        (
            await session.scalars(
                sa.select(Product.code)
                .join(Holding, Holding.product_id == Product.id)
                .where(Holding.customer_id == customer_id)
            )
        ).all()
    )

    # Derive a risk answer from persona / preferences / facts, if present.
    risk = _derive_risk(customer, preferences + facts)

    annual_income = customer.annual_income_paise
    return {
        "exists": True,
        "customer_id": str(customer_id),
        "name": customer.full_name,
        "city": customer.city,
        "state": customer.state,
        "occupation": customer.occupation,
        "segment": customer.segment,
        "annual_income_paise": annual_income,
        "income": annual_income,  # suitability-gate key
        "risk": risk,             # suitability-gate key
        "digital_maturity": customer.digital_maturity.value,
        "churn_risk": customer.churn_risk,
        "held_product_codes": held,
        "facts": facts,
        "preferences": preferences,
        "preferred_language": customer.preferred_language,  # vernacular chat
    }


def _derive_risk(customer: Customer, texts: list[str]) -> str | None:
    persona = customer.persona or {}
    risk = persona.get("risk_appetite") or persona.get("risk")
    if isinstance(risk, str) and risk:
        return risk
    blob = " ".join(texts).lower()
    for phrase, level in _RISK_WORDS.items():
        if phrase in blob:
            return level
    return None
