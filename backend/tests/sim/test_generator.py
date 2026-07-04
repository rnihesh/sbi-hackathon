from __future__ import annotations

import itertools
import json
from datetime import datetime

import pytest

from app.sim import generator
from app.sim.personas import Archetype, Persona, make_cohort


def _persona_of(archetype: Archetype, seed: int = 42, pool: int = 200) -> Persona:
    cohort = make_cohort(pool, seed)
    for p in cohort:
        if p.archetype == archetype:
            return p
    raise AssertionError(f"no {archetype} in a {pool}-persona cohort seeded {seed}")


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_generate_history_is_deterministic_first_50_txns() -> None:
    persona_a = _persona_of(Archetype.YOUNG_SALARIED_TECHIE)
    persona_b = _persona_of(Archetype.YOUNG_SALARIED_TECHIE)  # same seed -> identical persona
    assert persona_a.model_dump() == persona_b.model_dump()

    txns_a = generator.generate_history(persona_a, months=6, seed=42)
    txns_b = generator.generate_history(persona_b, months=6, seed=42)

    assert len(txns_a) >= 50 and len(txns_b) >= 50
    assert [t.model_dump() for t in txns_a[:50]] == [t.model_dump() for t in txns_b[:50]]


def test_generate_history_full_stream_is_byte_identical_across_runs() -> None:
    persona = _persona_of(Archetype.GIG_WORKER)
    txns_1 = generator.generate_history(persona, months=3, seed=99)
    txns_2 = generator.generate_history(persona, months=3, seed=99)
    assert [t.model_dump() for t in txns_1] == [t.model_dump() for t in txns_2]


def test_different_seed_changes_the_stream() -> None:
    persona = _persona_of(Archetype.YOUNG_SALARIED_TECHIE, seed=1)
    txns_1 = generator.generate_history(persona, months=3, seed=1)
    txns_2 = generator.generate_history(persona, months=3, seed=2)
    assert [t.event_id for t in txns_1] != [t.event_id for t in txns_2]


# ---------------------------------------------------------------------------
# Salary periodicity
# ---------------------------------------------------------------------------


def test_salary_credited_once_per_month_near_the_1st() -> None:
    persona = _persona_of(Archetype.YOUNG_SALARIED_TECHIE)
    txns = generator.generate_history(persona, months=12, seed=42)
    salary_txns = [t for t in txns if t.category == "salary"]

    assert len(salary_txns) == 12
    months_seen = {(t.ts.year, t.ts.month) for t in salary_txns}
    assert len(months_seen) == 12  # exactly one per calendar month
    for t in salary_txns:
        assert t.direction is generator.Direction.CREDIT
        assert t.channel is generator.Channel.NEFT
        assert 1 <= t.ts.day <= 3
        assert t.merchant == persona.employer


def test_retiree_pension_periodicity_and_quarterly_fd_interest() -> None:
    persona = _persona_of(Archetype.RETIREE)
    txns = generator.generate_history(persona, months=12, seed=42)
    pensions = [t for t in txns if t.category == "pension"]
    fd_interest = [t for t in txns if t.category == "fd_interest"]

    assert len(pensions) == 12
    assert len(fd_interest) == 4  # Mar/Jun/Sep/Dec


# ---------------------------------------------------------------------------
# Overdraft guard: balance must never go negative
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("archetype", list(Archetype))
def test_balance_never_negative(archetype: Archetype) -> None:
    cohort = make_cohort(60, seed=42)
    personas_of_type = [p for p in cohort if p.archetype == archetype]
    assert personas_of_type, f"expected at least one {archetype} in cohort"
    for persona in personas_of_type:
        txns = generator.generate_history(persona, months=12, seed=42)
        assert all(t.balance_after_paise >= 0 for t in txns), archetype


def test_balance_after_paise_is_chronologically_consistent() -> None:
    """Regression test: balance_after_paise must reflect true ts order.

    A prior bug applied balance mutations in a fixed code-emission order
    (income, rent, utilities, discretionary, ...) and only sorted the
    resulting list by `ts` afterwards -- so once sorted, the running balance
    trail no longer matched the displayed chronological order.
    """
    persona = _persona_of(Archetype.YOUNG_SALARIED_TECHIE)
    txns = generator.generate_history(persona, months=6, seed=42)
    assert txns == sorted(txns, key=lambda t: t.ts)

    balance = generator._initial_balance_paise(persona)
    for t in txns:
        if t.direction is generator.Direction.CREDIT:
            balance += t.amount_paise
        else:
            balance -= t.amount_paise
        assert balance == t.balance_after_paise
        assert balance >= 0


# ---------------------------------------------------------------------------
# generate_live
# ---------------------------------------------------------------------------


def test_generate_live_yields_chronological_infinite_stream() -> None:
    persona = _persona_of(Archetype.YOUNG_SALARIED_TECHIE)
    clock = generator.SimClock(sim_start=datetime(2024, 1, 1))
    live = generator.generate_live(persona, clock, seed=42)
    first_30 = list(itertools.islice(live, 30))
    assert len(first_30) == 30
    assert all(t.ts >= clock.sim_start for t in first_30)
    assert first_30 == sorted(first_30, key=lambda t: t.ts)


def test_generate_live_matches_generate_history_prefix() -> None:
    """Same seed/state semantics -> generate_live's early days line up with
    the equivalent slice of generate_history."""
    persona = _persona_of(Archetype.YOUNG_SALARIED_TECHIE)
    clock = generator.SimClock(
        sim_start=datetime.combine(generator.DEFAULT_HISTORY_START, datetime.min.time())
    )
    history = generator.generate_history(persona, months=1, seed=42)
    live = generator.generate_live(persona, clock, seed=42)
    live_prefix = list(itertools.islice(live, len(history)))
    assert [t.model_dump() for t in live_prefix] == [t.model_dump() for t in history]


# ---------------------------------------------------------------------------
# Envelope contract (golden keys)
# ---------------------------------------------------------------------------


def test_envelope_golden_keys_are_stable() -> None:
    persona = _persona_of(Archetype.YOUNG_SALARIED_TECHIE)
    txns = generator.generate_history(persona, months=1, seed=42)
    assert txns

    envelope = generator.to_envelope(txns[0])

    assert set(envelope.keys()) == {"event_id", "customer_id", "type", "ts", "payload"}
    assert envelope["type"] == "transaction"
    assert envelope["event_id"] == txns[0].event_id
    assert envelope["customer_id"] == txns[0].customer_id
    assert envelope["ts"] == envelope["payload"]["ts"]

    expected_payload_keys = {
        "event_id",
        "customer_id",
        "ts",
        "amount_paise",
        "direction",
        "channel",
        "merchant",
        "mcc",
        "category",
        "balance_after_paise",
        "description",
    }
    assert set(envelope["payload"].keys()) == expected_payload_keys

    # Must be plain-JSON-serializable (no datetimes/enums leaking through).
    json.dumps(envelope)


def test_envelope_contract_holds_for_every_txn_in_a_stream() -> None:
    persona = _persona_of(Archetype.SMALL_BUSINESS_OWNER)
    txns = generator.generate_history(persona, months=2, seed=7)
    for t in txns:
        envelope = generator.to_envelope(t)
        assert set(envelope.keys()) == {"event_id", "customer_id", "type", "ts", "payload"}
        json.dumps(envelope)
