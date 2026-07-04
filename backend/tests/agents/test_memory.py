"""Memory tests: cosine + recency recall ordering, profile facts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.agents import memory
from app.models.customer import Customer
from app.models.enums import MemoryKind
from app.models.memory import AgentMemory


async def _make_customer(db, **kwargs) -> Customer:  # type: ignore[no-untyped-def]
    customer = Customer(full_name=kwargs.pop("full_name", "Mem User"), **kwargs)
    db.add(customer)
    await db.flush()
    return customer


async def test_recall_ranks_by_similarity(db, fake_embedder) -> None:  # type: ignore[no-untyped-def]
    customer = await _make_customer(db)
    await memory.remember(db, customer.id, "episodic", "alpha topic note", embedder=fake_embedder)
    await memory.remember(db, customer.id, "episodic", "beta topic note", embedder=fake_embedder)
    await db.commit()

    hits = await memory.recall(db, customer.id, "alpha please", k=2, embedder=fake_embedder)
    assert hits[0].text == "alpha topic note"
    assert hits[0].similarity > hits[-1].similarity


async def test_recall_prefers_recent_when_similarity_ties(db, fake_embedder) -> None:  # type: ignore[no-untyped-def]
    customer = await _make_customer(db)
    now = datetime.now(UTC)
    vec = fake_embedder.vector_fn("alpha")
    old = AgentMemory(
        customer_id=customer.id, kind=MemoryKind.EPISODIC, text="alpha old",
        embedding=vec,
    )
    old.created_at = now - timedelta(days=90)
    fresh = AgentMemory(
        customer_id=customer.id, kind=MemoryKind.EPISODIC, text="alpha fresh",
        embedding=vec,
    )
    fresh.created_at = now
    db.add_all([old, fresh])
    await db.commit()

    hits = await memory.recall(db, customer.id, "alpha", k=2, embedder=fake_embedder)
    assert hits[0].text == "alpha fresh"  # recency decay breaks the similarity tie
    assert hits[0].score > hits[1].score


async def test_profile_facts_exposes_income_and_risk(db, fake_embedder) -> None:  # type: ignore[no-untyped-def]
    customer = await _make_customer(
        db, full_name="Priya", annual_income_paise=600_000 * 100,
        city="Pune", persona={"risk_appetite": "high"},
    )
    await memory.remember(
        db, customer.id, "fact", "prefers digital banking", embedder=fake_embedder
    )
    await db.commit()

    facts = await memory.profile_facts(db, customer.id)
    assert facts["income"] == 600_000 * 100
    assert facts["risk"] == "high"
    assert "prefers digital banking" in facts["facts"]
    assert facts["name"] == "Priya"
