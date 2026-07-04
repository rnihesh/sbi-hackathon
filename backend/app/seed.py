"""Full-stack DB seeding: sim cohort -> real Customer/Account/Transaction/Holding/
Lead/AgentMemory rows.

Usage::

    uv run python -m app.seed --cohort 20 --months 6 --seed 42
    uv run python -m app.seed --cohort 20 --months 6 --seed 42 --reset

Seeding ID contract
--------------------
``Customer.id == uuid.UUID(persona.id)`` - ``app.sim.personas.Persona.id`` is already
a stable ``uuid5`` string (deterministic from ``(seed, index)``), so no extra mapping
column is needed: the event consumer's ``txn.events`` envelopes carry
``customer_id = persona.id`` and resolve straight to ``Customer.id``.

Idempotent by construction: personas whose ``Customer.id`` already exists are
skipped entirely (safe to re-run the same ``--cohort/--seed`` without duplicating
data). ``--reset`` instead truncates every domain table first for a clean slate -
it never touches ``users``/``credentials``/``otp_codes`` (real login identities).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import date, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.core.logging import get_logger, setup_logging
from app.models.banking import Account, Transaction
from app.models.crm import Lead
from app.models.customer import Customer
from app.models.enums import (
    AccountStatus,
    AccountType,
    DigitalMaturity,
    LeadStage,
    MemoryKind,
)
from app.models.memory import AgentMemory
from app.services import products
from app.sim import generator, personas

logger = get_logger(__name__)

# Domain tables truncated by `--reset`, in an order TRUNCATE...CASCADE doesn't care
# about (CASCADE follows FKs) but that reads top-down for a human skimming this file.
# Deliberately excludes `products` (idempotent catalog upsert handles it) and every
# identity table (`users`, `credentials`, `otp_codes`).
_RESET_TABLES: tuple[str, ...] = (
    "agent_steps",
    "agent_runs",
    "llm_calls",
    "audit_logs",
    "messages",
    "conversations",
    "nudges",
    "proposals",
    "life_events",
    "agent_memories",
    "holdings",
    "leads",
    "transactions",
    "accounts",
    "customers",
)

_SEGMENT_BY_ARCHETYPE: dict[personas.Archetype, str] = {
    personas.Archetype.YOUNG_SALARIED_TECHIE: "salaried",
    personas.Archetype.SMALL_BUSINESS_OWNER: "business",
    personas.Archetype.GIG_WORKER: "gig",
    personas.Archetype.STUDENT: "student",
    personas.Archetype.HOMEMAKER: "homemaker",
    personas.Archetype.RETIREE: "retired",
}

_EXTRA_LEAD_COUNT = 3
_EXTRA_LEAD_STAGES = (LeadStage.NEW, LeadStage.QUALIFIED, LeadStage.CONTACTED)


def _digital_maturity_enum(score: float) -> DigitalMaturity:
    if score < 0.4:
        return DigitalMaturity.LOW
    if score < 0.75:
        return DigitalMaturity.MEDIUM
    return DigitalMaturity.HIGH


def _synthetic_email(persona: personas.Persona) -> str:
    """Deterministic, obviously-synthetic email (never a real domain)."""
    local = persona.name.split()[0].lower().replace(".", "")
    return f"{local}.{persona.id[:8]}@sarathi-sim.example"


async def _reset_domain_tables(session: AsyncSession) -> None:
    table_list = ", ".join(_RESET_TABLES)
    await session.execute(sa.text(f"TRUNCATE {table_list} RESTART IDENTITY CASCADE"))
    logger.info("seed_reset_domain_tables", tables=_RESET_TABLES)


def _history_start(months: int) -> date:
    """Anchor the seeded transaction history so it ends at (roughly) today.

    The sim generator's own ``DEFAULT_HISTORY_START`` is a fixed 2024 date, kept
    deterministic for unit tests. For the live DB cohort we instead want the
    history to run right up to the present so that console-injected life events
    (which are dated from ``date.today()``) continue the same timeline: the
    event consumer's trailing-window rules (salary-change etc.) can only compare
    an injected credit against a baseline that falls inside their look-back
    window. A 2-year gap between a fixed-2024 baseline and today-dated events
    would leave every injected event with no baseline to deviate from.
    """
    return date.today() - timedelta(days=months * 30)


async def _seed_persona(
    session: AsyncSession,
    persona: personas.Persona,
    *,
    months: int,
    seed: int,
    history_start: date,
) -> dict[str, int] | None:
    """Seed one persona's Customer/Account/Transaction/Holding/Lead/Memory rows.

    Returns row counts, or ``None`` if this persona's Customer already existed
    (idempotent skip).
    """
    customer_id = uuid.UUID(persona.id)
    existing = await session.get(Customer, customer_id)
    if existing is not None:
        return None

    segment = _SEGMENT_BY_ARCHETYPE.get(persona.archetype)
    customer = Customer(
        id=customer_id,
        full_name=persona.name,
        email=_synthetic_email(persona),
        phone=None,
        city=persona.city,
        occupation=persona.occupation,
        annual_income_paise=persona.monthly_income_paise * 12,
        segment=segment,
        persona=persona.model_dump(mode="json"),
        digital_maturity=_digital_maturity_enum(persona.digital_maturity),
    )
    session.add(customer)
    await session.flush()

    account = Account(
        customer_id=customer.id,
        type=AccountType.SAVINGS,
        balance_paise=0,
        status=AccountStatus.ACTIVE,
        label="Primary Savings",
    )
    session.add(account)
    await session.flush()

    state = generator.new_state(persona, seed, start_date=history_start)
    txns = generator.generate_history(
        persona, months, seed, state=state, start_date=history_start
    )
    if txns:
        rows = [
            {
                "id": uuid.uuid4(),
                "account_id": account.id,
                "event_id": t.event_id,
                "ts": t.ts,
                "amount_paise": t.amount_paise,
                "direction": t.direction.value,
                "channel": t.channel.value,
                "merchant": t.merchant,
                "mcc": t.mcc,
                "category": t.category,
                "balance_after_paise": t.balance_after_paise,
                "description": t.description,
            }
            for t in txns
        ]
        await session.execute(sa.insert(Transaction), rows)
    account.balance_paise = state.balance_paise
    await session.flush()

    holdings_created = 0
    for code in persona.products_held:
        await products.activate_holding(session, customer_id=customer.id, product_code=code)
        holdings_created += 1

    lead = Lead(
        customer_id=customer.id,
        source="seed",
        name=persona.name,
        email=customer.email,
        phone=None,
        intent_score=1.0,
        stage=LeadStage.CONVERTED,
        notes="Synthetic cohort member onboarded via seed script.",
    )
    session.add(lead)

    session.add(
        AgentMemory(
            customer_id=customer.id,
            kind=MemoryKind.EPISODIC,
            text=(
                f"Welcomed {persona.name} to Sarathi as a {persona.archetype.value} "
                f"customer in {persona.city}."
            ),
            embedding=None,
        )
    )

    return {"transactions": len(txns), "holdings": holdings_created}


async def _seed_extra_leads(session: AsyncSession, *, seed: int) -> int:
    """A handful of not-yet-converted prospects, for a realistic acquisition funnel."""
    import random

    from faker import Faker

    rng = random.Random(personas.derived_seed(seed, "seed_extra_leads"))
    fake = Faker("en_IN")
    fake.seed_instance(personas.derived_seed(seed, "seed_extra_leads", "faker"))

    created = 0
    for i in range(_EXTRA_LEAD_COUNT):
        stage = _EXTRA_LEAD_STAGES[i % len(_EXTRA_LEAD_STAGES)]
        name = fake.name()
        lead = Lead(
            customer_id=None,
            source="web",
            name=name,
            email=f"{name.split()[0].lower()}.{i}@sarathi-prospect.example",
            phone=None,
            intent_score=round(rng.uniform(0.2, 0.8), 3),
            stage=stage,
            notes="Synthetic prospect (not yet converted) for funnel realism.",
        )
        session.add(lead)
        created += 1
    return created


async def seed(
    *, cohort: int, seed_value: int, months: int, reset: bool
) -> dict[str, int]:
    sessionmaker = get_sessionmaker()
    summary = {
        "customers": 0,
        "skipped_existing": 0,
        "transactions": 0,
        "holdings": 0,
        "leads": 0,
        "memories": 0,
    }

    async with sessionmaker() as session:
        if reset:
            await _reset_domain_tables(session)
            await session.commit()

        await products.seed_catalog(session)
        await session.commit()

        history_start = _history_start(months)
        cohort_personas = personas.make_cohort(cohort, seed_value)
        for persona in cohort_personas:
            counts = await _seed_persona(
                session, persona, months=months, seed=seed_value, history_start=history_start
            )
            if counts is None:
                summary["skipped_existing"] += 1
                continue
            summary["customers"] += 1
            summary["transactions"] += counts["transactions"]
            summary["holdings"] += counts["holdings"]
            summary["leads"] += 1
            summary["memories"] += 1
            await session.commit()

        extra_leads = await _seed_extra_leads(session, seed=seed_value)
        summary["leads"] += extra_leads
        await session.commit()

    return summary


def _print_summary(summary: dict[str, int], *, cohort: int, months: int, seed_value: int) -> None:
    print(f"\nSarathi seed complete (cohort={cohort}, months={months}, seed={seed_value})")
    print("-" * 60)
    for key in ("customers", "skipped_existing", "transactions", "holdings", "leads", "memories"):
        print(f"  {key:<20} {summary[key]:>10,}")
    print("-" * 60)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sarathi full-stack DB seeder.")
    parser.add_argument("--cohort", type=int, default=20)
    parser.add_argument("--months", type=int, default=6)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--reset", action="store_true", help="Truncate domain tables before seeding."
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    setup_logging()
    parser = build_arg_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    summary = asyncio.run(
        seed(cohort=args.cohort, seed_value=args.seed, months=args.months, reset=args.reset)
    )
    _print_summary(summary, cohort=args.cohort, months=args.months, seed_value=args.seed)


if __name__ == "__main__":
    main()
