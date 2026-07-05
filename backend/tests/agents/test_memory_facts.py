"""Memory-intelligence tests: dedup-aware fact insert, episodic pruning, the
FACT/PREFERENCE recall boost, the known-facts directive, and its inclusion in
every specialist's system prompt."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from app.agents import memory
from app.agents.state import new_state
from app.agents.supervisor import run_specialist
from app.models.customer import Customer
from app.models.enums import MemoryKind
from app.models.memory import AgentMemory
from tests.agents.conftest import FakeRouter, ScriptedHandler


class _NoEmbedder:
    """Embedder double reporting no provider (forces the exact-text dedup floor)."""

    def available(self) -> bool:
        return False

    async def embed(self, text: str) -> list[float]:  # pragma: no cover - never called
        raise AssertionError("embed must not be called when unavailable")

    async def embed_many(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover
        return []


async def _make_customer(db, **kwargs) -> Customer:  # type: ignore[no-untyped-def]
    customer = Customer(full_name=kwargs.pop("full_name", "Fact User"), **kwargs)
    db.add(customer)
    await db.flush()
    return customer


# ---------------------------------------------------------------------------
# Dedup-aware fact insert
# ---------------------------------------------------------------------------


async def test_remember_fact_skips_semantic_duplicate(db, fake_embedder) -> None:  # type: ignore[no-untyped-def]
    customer = await _make_customer(db)
    first = await memory.remember_fact(
        db, customer.id, "fact", "has an alpha portfolio", embedder=fake_embedder
    )
    assert first is not None
    # Same fake-embedder axis ("alpha") -> cosine 1.0 -> duplicate, skipped.
    dup = await memory.remember_fact(
        db, customer.id, "fact", "alpha holdings are large", embedder=fake_embedder
    )
    assert dup is None
    # Different axis ("beta") -> orthogonal -> not a duplicate, stored.
    fresh = await memory.remember_fact(
        db, customer.id, "preference", "prefers beta funds", embedder=fake_embedder
    )
    assert fresh is not None
    await db.commit()

    rows = list(
        (
            await db.scalars(
                sa.select(AgentMemory).where(AgentMemory.customer_id == customer.id)
            )
        ).all()
    )
    assert len(rows) == 2


async def test_remember_fact_casefold_dedup_without_embedder(db) -> None:  # type: ignore[no-untyped-def]
    customer = await _make_customer(db)
    emb = _NoEmbedder()
    first = await memory.remember_fact(db, customer.id, "fact", "Has two kids", embedder=emb)
    assert first is not None
    assert first.embedding is None  # no provider -> stored without a vector
    dup = await memory.remember_fact(db, customer.id, "fact", "  has TWO kids ", embedder=emb)
    assert dup is None  # exact casefold match is the only signal, and it fires
    await db.commit()

    rows = list(
        (
            await db.scalars(
                sa.select(AgentMemory).where(AgentMemory.customer_id == customer.id)
            )
        ).all()
    )
    assert len(rows) == 1


async def test_remember_fact_ignores_blank_text(db, fake_embedder) -> None:  # type: ignore[no-untyped-def]
    customer = await _make_customer(db)
    blank = await memory.remember_fact(db, customer.id, "fact", "   ", embedder=fake_embedder)
    assert blank is None


# ---------------------------------------------------------------------------
# Recall boost
# ---------------------------------------------------------------------------


async def test_recall_boosts_facts_over_episodic(db, fake_embedder) -> None:  # type: ignore[no-untyped-def]
    customer = await _make_customer(db)
    vec = fake_embedder.vector_fn("alpha")
    now = datetime.now(UTC)
    episodic = AgentMemory(
        customer_id=customer.id, kind=MemoryKind.EPISODIC, text="alpha episodic", embedding=vec
    )
    fact = AgentMemory(
        customer_id=customer.id, kind=MemoryKind.FACT, text="alpha fact", embedding=vec
    )
    episodic.created_at = now
    fact.created_at = now  # identical similarity AND recency -> boost breaks the tie
    db.add_all([episodic, fact])
    await db.commit()

    hits = await memory.recall(db, customer.id, "alpha", k=2, embedder=fake_embedder)
    assert hits[0].text == "alpha fact"
    assert hits[0].kind == "fact"
    assert hits[0].score > hits[1].score


# ---------------------------------------------------------------------------
# Pruning
# ---------------------------------------------------------------------------


async def test_prune_deletes_stale_episodic_only(db) -> None:  # type: ignore[no-untyped-def]
    customer = await _make_customer(db)
    now = datetime.now(UTC)

    def _mem(kind: MemoryKind, text: str, age_days: float) -> AgentMemory:
        row = AgentMemory(customer_id=customer.id, kind=kind, text=text)
        row.created_at = now - timedelta(days=age_days)
        return row

    db.add_all(
        [
            _mem(MemoryKind.EPISODIC, "old1", 100),
            _mem(MemoryKind.EPISODIC, "old2", 99),
            _mem(MemoryKind.EPISODIC, "old3", 98),
            _mem(MemoryKind.EPISODIC, "recent1", 1),
            _mem(MemoryKind.EPISODIC, "recent2", 0),
            _mem(MemoryKind.FACT, "durable fact", 100),
            _mem(MemoryKind.PREFERENCE, "durable pref", 100),
        ]
    )
    await db.commit()

    # keep_recent=2: the two newest episodic are kept; the 3 older ones are all
    # beyond the 90-day cutoff -> deleted. Facts/preferences are never touched.
    deleted = await memory.prune_memories(db, now=now, keep_recent=2, retention_days=90)
    await db.commit()
    assert deleted == 3

    remaining = set(
        (
            await db.scalars(
                sa.select(AgentMemory.text).where(AgentMemory.customer_id == customer.id)
            )
        ).all()
    )
    assert remaining == {"recent1", "recent2", "durable fact", "durable pref"}


async def test_prune_keeps_recent_episodic_within_keep_window(db) -> None:  # type: ignore[no-untyped-def]
    customer = await _make_customer(db)
    now = datetime.now(UTC)
    # Two very old episodic rows, but keep_recent=5 protects them (< 5 total).
    for i in range(2):
        row = AgentMemory(
            customer_id=customer.id, kind=MemoryKind.EPISODIC, text=f"ancient{i}"
        )
        row.created_at = now - timedelta(days=365)
        db.add(row)
    await db.commit()

    deleted = await memory.prune_memories(db, now=now, keep_recent=5, retention_days=90)
    await db.commit()
    assert deleted == 0  # both survive - they are within the newest-N keep window


async def test_prune_respects_cap_oldest_first(db) -> None:  # type: ignore[no-untyped-def]
    customer = await _make_customer(db)
    now = datetime.now(UTC)
    for i in range(4):
        row = AgentMemory(customer_id=customer.id, kind=MemoryKind.EPISODIC, text=f"old{i}")
        row.created_at = now - timedelta(days=100 + i)  # old3 is the oldest
        db.add(row)
    await db.commit()

    deleted = await memory.prune_memories(
        db, now=now, keep_recent=0, retention_days=90, cap=1
    )
    await db.commit()
    assert deleted == 1
    remaining = set(
        (
            await db.scalars(
                sa.select(AgentMemory.text).where(AgentMemory.customer_id == customer.id)
            )
        ).all()
    )
    assert "old3" not in remaining  # the single oldest went first


# ---------------------------------------------------------------------------
# Known-facts directive
# ---------------------------------------------------------------------------


def test_known_facts_directive_renders_facts_then_prefs() -> None:
    line = memory.known_facts_directive(
        {"facts": ["has two kids", "works at Infosys"], "preferences": ["is risk-averse"]}
    )
    assert line.startswith("Known about this customer:")
    assert "has two kids" in line
    assert "is risk-averse" in line


def test_known_facts_directive_caps_at_five() -> None:
    facts = [f"fact {i}" for i in range(8)]
    line = memory.known_facts_directive({"facts": facts, "preferences": ["pref"]})
    # Only the first 5 items make it in (facts lead, capped).
    assert "fact 4" in line
    assert "fact 5" not in line
    assert "pref" not in line


def test_known_facts_directive_empty_when_nothing_known() -> None:
    assert memory.known_facts_directive({"facts": [], "preferences": []}) == ""
    assert memory.known_facts_directive({}) == ""


# ---------------------------------------------------------------------------
# Specialist prompt inclusion
# ---------------------------------------------------------------------------


async def test_specialist_prompt_includes_known_facts(db, fake_embedder, make_ctx) -> None:  # type: ignore[no-untyped-def]
    customer = await _make_customer(db, full_name="Asha")
    await memory.remember(
        db, customer.id, MemoryKind.FACT, "has two school-age kids", embedder=fake_embedder
    )
    await memory.remember(
        db, customer.id, MemoryKind.PREFERENCE, "is risk-averse", embedder=fake_embedder
    )
    await db.commit()

    router = FakeRouter(ScriptedHandler(default_text="Here is some help."))
    ctx = await make_ctx(router, customer_id=customer.id)
    state = new_state(conversation_id="c", customer_id=str(customer.id), user_text="help with UPI")
    config = {"configurable": {"ctx": ctx}}

    def _builder(_ctx, _state, _profile, _memories) -> str:  # type: ignore[no-untyped-def]
        return "BASE SPECIALIST SYSTEM"

    await run_specialist(
        state, config,
        agent_name="adoption", node_name="adoption",
        system_builder=_builder, tools={},
    )

    systems = [c["system"] for c in router.calls if c.get("system")]
    assert any(
        "BASE SPECIALIST SYSTEM" in s
        and "Known about this customer:" in s
        and "has two school-age kids" in s
        for s in systems
    )
