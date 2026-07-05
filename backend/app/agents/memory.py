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
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy.engine import CursorResult
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

# Durable memories (facts/preferences) get a flat score bump so they rank above
# episodic memories at equal similarity - the things the bank actually knows about
# a customer should win recall over a stray conversational echo.
_KIND_BOOST: dict[MemoryKind, float] = {MemoryKind.FACT: 0.1, MemoryKind.PREFERENCE: 0.1}

FACT_DEDUP_THRESHOLD = 0.92
"""Cosine similarity at/above which a candidate fact counts as a duplicate (skip insert)."""

EPISODIC_RETENTION_DAYS = 90
"""Episodic memories older than this are eligible for pruning (facts/prefs are kept)."""

EPISODIC_KEEP_RECENT = 200
"""Always keep at least this many newest episodic memories per customer, any age."""

_PRUNE_MAX_ROWS = 500
"""Per-call cap on deletes so a large backlog drains over several ticks, never in one."""

_KNOWN_FACTS_LIMIT = 5
"""How many FACT/PREFERENCE texts are inlined into a specialist's system prompt."""


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
        boost = _KIND_BOOST.get(mem.kind, 0.0)
        score = similarity * math.exp(-age_days / _DECAY_DAYS) + boost
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


# ---------------------------------------------------------------------------
# Durable facts: dedup-aware insert
# ---------------------------------------------------------------------------


async def remember_fact(
    session: AsyncSession,
    customer_id: uuid.UUID,
    kind: MemoryKind | str,
    text: str,
    *,
    embedder: Embedder | None = None,
) -> AgentMemory | None:
    """Store a durable FACT/PREFERENCE unless a near-duplicate already exists.

    Dedup is semantic when an embedder is configured (cosine similarity
    ``>= FACT_DEDUP_THRESHOLD`` against the customer's existing facts/preferences),
    with an always-on exact casefold guard as a floor (and the sole check when no
    embedder is available). Returns the stored row, or ``None`` when skipped as a
    duplicate or empty.
    """
    embedder = embedder or get_embedder()
    text = " ".join(text.split()).strip()
    if not text:
        return None
    if await _is_duplicate_fact(session, customer_id, text, embedder):
        return None
    return await remember(session, customer_id, kind, text, embedder=embedder)


async def _is_duplicate_fact(
    session: AsyncSession, customer_id: uuid.UUID, text: str, embedder: Embedder
) -> bool:
    """True if ``text`` duplicates an existing FACT/PREFERENCE for the customer."""
    norm = text.casefold()
    existing_texts = list(
        (
            await session.scalars(
                sa.select(AgentMemory.text).where(
                    AgentMemory.customer_id == customer_id,
                    AgentMemory.kind.in_([MemoryKind.FACT, MemoryKind.PREFERENCE]),
                )
            )
        ).all()
    )
    if any(" ".join(t.split()).casefold() == norm for t in existing_texts):
        return True
    if not embedder.available():
        return False  # exact-text is the only available signal

    qvec = await embedder.embed(text)
    nearest = await session.scalar(
        sa.select(AgentMemory.embedding.cosine_distance(qvec))
        .where(
            AgentMemory.customer_id == customer_id,
            AgentMemory.kind.in_([MemoryKind.FACT, MemoryKind.PREFERENCE]),
            AgentMemory.embedding.is_not(None),
        )
        .order_by(AgentMemory.embedding.cosine_distance(qvec))
        .limit(1)
    )
    if nearest is None:
        return False
    return (1.0 - float(nearest)) >= FACT_DEDUP_THRESHOLD


# ---------------------------------------------------------------------------
# Decay / pruning (called from the scheduler tick)
# ---------------------------------------------------------------------------


async def prune_memories(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    keep_recent: int = EPISODIC_KEEP_RECENT,
    retention_days: int = EPISODIC_RETENTION_DAYS,
    cap: int = _PRUNE_MAX_ROWS,
) -> int:
    """Delete stale EPISODIC memories; keep FACT/PREFERENCE forever.

    A row is pruned iff it is EPISODIC, older than ``retention_days``, AND not among
    the newest ``keep_recent`` episodic memories for its customer. Deterministic;
    caps deletes at ``cap`` per call so a large backlog drains over several ticks.
    Returns the number of rows deleted. Does not commit.
    """
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=retention_days)

    ranked = (
        sa.select(
            AgentMemory.id.label("id"),
            AgentMemory.created_at.label("created_at"),
            sa.func.row_number()
            .over(
                partition_by=AgentMemory.customer_id,
                order_by=AgentMemory.created_at.desc(),
            )
            .label("rn"),
        )
        .where(AgentMemory.kind == MemoryKind.EPISODIC)
        .subquery()
    )
    to_delete = (
        sa.select(ranked.c.id)
        .where(ranked.c.rn > keep_recent, ranked.c.created_at < cutoff)
        .order_by(ranked.c.created_at)
        .limit(cap)
    )
    result = cast(
        "CursorResult[Any]",
        await session.execute(sa.delete(AgentMemory).where(AgentMemory.id.in_(to_delete))),
    )
    return max(int(result.rowcount), 0)


# ---------------------------------------------------------------------------
# Known-facts directive (inlined into every specialist's system prompt)
# ---------------------------------------------------------------------------


def known_facts_directive(profile: dict[str, object]) -> str:
    """Render the customer's top facts/preferences as a system-prompt line.

    Returns ``""`` when nothing durable is known, so callers can append
    unconditionally. Facts lead, then preferences, capped at ``_KNOWN_FACTS_LIMIT``.
    """
    facts = _as_text_list(profile.get("facts"))
    prefs = _as_text_list(profile.get("preferences"))
    items = (facts + prefs)[:_KNOWN_FACTS_LIMIT]
    if not items:
        return ""
    return "Known about this customer: " + "; ".join(items) + "."


def _as_text_list(value: object) -> list[str]:
    """Coerce a profile value to a list of non-empty strings (defensive on shape)."""
    if not isinstance(value, list | tuple):
        return []
    return [str(v) for v in value if str(v).strip()]
