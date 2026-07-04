"""Batch seed script: deterministic cohort + historical transactions to JSONL.

Writes ``backend/app/sim/out/{personas,transactions,ground_truth}.jsonl`` and,
with ``--publish``, backfills every transaction onto the ``txn.events`` Redis
Stream (same envelope contract as ``runner.py``, via
:func:`app.sim.generator.to_envelope`).

Usage::

    uv run python -m app.sim.seed --cohort 20 --seed 42 --months 6
    uv run python -m app.sim.seed --cohort 20 --seed 42 --months 6 --publish --life-events 3
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import orjson

from app.sim import events, generator, personas

DEFAULT_REDIS_URL = "redis://localhost:6379/0"
STREAM_NAME = "txn.events"
DEFAULT_OUT_DIR = Path(__file__).resolve().parent / "out"


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(orjson.dumps(row).decode("utf-8"))
            f.write("\n")


def _pick_life_event_personas(
    cohort: list[personas.Persona], k: int, seed: int
) -> dict[str, events.LifeEventType]:
    if k <= 0 or not cohort:
        return {}
    rng = random.Random(personas.derived_seed(seed, "seed_life_events"))
    k = min(k, len(cohort))
    chosen = rng.sample(cohort, k)
    event_types = list(events.LifeEventType)
    return {p.id: rng.choice(event_types) for p in chosen}


def _generate_persona_history(
    persona: personas.Persona,
    months: int,
    seed: int,
    life_event: events.LifeEventType | None,
) -> tuple[list[generator.Txn], events.GroundTruthEvent | None]:
    state = generator.new_state(persona, seed, start_date=generator.DEFAULT_HISTORY_START)
    if life_event is None or months < 2:
        txns = generator.generate_history(
            persona, months, seed, state=state, start_date=generator.DEFAULT_HISTORY_START
        )
        return txns, None

    rng = random.Random(personas.derived_seed(seed, persona.id, "seed_life_event_split"))
    first_months = rng.randint(1, months - 1)
    second_months = months - first_months

    first_segment = generator.generate_history(
        persona, first_months, seed, state=state, start_date=generator.DEFAULT_HISTORY_START
    )
    assert state.last_generated_date is not None
    trigger_ts = datetime.combine(state.last_generated_date, datetime.min.time())
    script = events.REGISTRY[life_event]
    gt = script.apply(persona, state, trigger_ts)
    second_segment = generator.generate_history(persona, second_months, seed, state=state)
    return first_segment + second_segment, gt


def build_seed_data(
    cohort_size: int, seed: int, months: int, life_events_count: int
) -> tuple[list[personas.Persona], list[generator.Txn], list[events.GroundTruthEvent]]:
    cohort = personas.make_cohort(cohort_size, seed)
    life_event_map = _pick_life_event_personas(cohort, life_events_count, seed)

    all_txns: list[generator.Txn] = []
    ground_truth: list[events.GroundTruthEvent] = []
    for persona in cohort:
        txns, gt = _generate_persona_history(persona, months, seed, life_event_map.get(persona.id))
        all_txns.extend(txns)
        if gt is not None:
            ground_truth.append(gt)

    all_txns.sort(key=lambda t: (t.customer_id, t.ts))
    return cohort, all_txns, ground_truth


async def _publish_backfill(txns: list[generator.Txn], redis_url: str) -> None:
    import redis.asyncio as aioredis

    redis_client = aioredis.from_url(redis_url)
    try:
        for txn in txns:
            envelope = generator.to_envelope(txn)
            await redis_client.xadd(STREAM_NAME, {"data": orjson.dumps(envelope)})
    finally:
        await redis_client.aclose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Sarathi sim seed data generator.")
    parser.add_argument("--cohort", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--months", type=int, default=6)
    parser.add_argument("--life-events", type=int, default=3)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--publish", action="store_true", help="Backfill onto the Redis stream too."
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    cohort, txns, ground_truth = build_seed_data(
        args.cohort, args.seed, args.months, args.life_events
    )

    _write_jsonl(args.out_dir / "personas.jsonl", [p.model_dump(mode="json") for p in cohort])
    _write_jsonl(args.out_dir / "transactions.jsonl", [t.model_dump(mode="json") for t in txns])
    _write_jsonl(
        args.out_dir / "ground_truth.jsonl", [g.model_dump(mode="json") for g in ground_truth]
    )
    print(
        f"Seeded {len(cohort)} personas, {len(txns)} transactions, "
        f"{len(ground_truth)} ground-truth life events -> {args.out_dir}"
    )

    if args.publish:
        redis_url = os.environ.get("REDIS_URL", DEFAULT_REDIS_URL)
        asyncio.run(_publish_backfill(txns, redis_url))
        print(f"Published {len(txns)} transactions to '{STREAM_NAME}' at {redis_url}")


if __name__ == "__main__":
    main()
