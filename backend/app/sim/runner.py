"""Async publisher: streams a live, time-compressed cohort to Redis.

Publishes each transaction as JSON to the ``txn.events`` Redis Stream via
``XADD`` with a single field ``data`` holding orjson-encoded bytes of the
envelope produced by :func:`app.sim.generator.to_envelope`.

Deliberately does **not** import ``app.core`` (owned by a parallel wave):
``REDIS_URL`` is read straight from the environment. This module is a
standalone CLI (``python -m app.sim.runner``); it has no FastAPI dependency.

Life events: ``--life-events K`` picks K distinct random personas from the
cohort and schedules one of the six scripted life events at a staggered
sim-time within the run. Ground truth (what happened, to whom, when) is
printed to stdout as it fires and appended to ``ground_truth.jsonl`` in the
output directory -- this is the label set future detection agents are graded
against.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
import time as time_module
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import orjson

from app.sim import events, generator, personas

DEFAULT_REDIS_URL = "redis://localhost:6379/0"
STREAM_NAME = "txn.events"
OUT_DIR = Path(__file__).resolve().parent / "out"


@dataclass(frozen=True)
class ScheduledLifeEvent:
    persona_id: str
    event_type: events.LifeEventType
    trigger_sim_time: datetime


def _schedule_life_events(
    cohort: list[personas.Persona],
    sim_start: datetime,
    run_days: int,
    k: int,
    seed: int,
) -> dict[str, list[ScheduledLifeEvent]]:
    """Pick K distinct personas and stagger one life event each across the run."""
    if k <= 0 or not cohort:
        return {}
    rng = random.Random(personas.derived_seed(seed, "life_event_schedule"))
    k = min(k, len(cohort))
    chosen = rng.sample(cohort, k)
    event_types = list(events.LifeEventType)
    schedule: dict[str, list[ScheduledLifeEvent]] = {}
    for persona in chosen:
        event_type = rng.choice(event_types)
        offset_days = rng.uniform(0.5, max(1.0, run_days - 0.5))
        trigger_time = sim_start + timedelta(days=offset_days)
        schedule.setdefault(persona.id, []).append(
            ScheduledLifeEvent(persona.id, event_type, trigger_time)
        )
    return schedule


def _write_ground_truth(path: Path, gt: events.GroundTruthEvent) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(gt.model_dump_json())
        f.write("\n")


async def _publish(redis_client: AsyncRedisLike, envelope: dict[str, object]) -> None:
    await redis_client.xadd(STREAM_NAME, {"data": orjson.dumps(envelope)})


class AsyncRedisLike(Protocol):
    """Structural type for the subset of redis.asyncio.Redis we use.

    A `Protocol` (not a plain class) so both the real `redis.asyncio.Redis`
    and test fakes satisfy it structurally, without either inheriting from
    the other. Deliberately `Any`-typed: `redis-py`'s real `xadd` stub is
    far broader (accepts bytes/str/memoryview keys and values, trimming
    options, etc.) than anything we need here, and pinning tighter types
    just fights that stub under `mypy --strict` for no real safety gain --
    the only thing this protocol needs to pin down is *which methods*
    `runner.py` calls, not their exact signatures.
    """

    def xadd(self, name: Any, fields: Any) -> Awaitable[Any]: ...
    def aclose(self) -> Awaitable[Any]: ...


async def _run_persona_live(
    persona: personas.Persona,
    seed: int,
    sim_clock: generator.SimClock,
    speed: float,
    redis_client: AsyncRedisLike,
    scheduled: list[ScheduledLifeEvent],
    ground_truth_path: Path,
    stop_after_days: float,
) -> None:
    state = generator.new_state(persona, seed, start_date=sim_clock.sim_start.date())
    gen = generator.generate_live(persona, sim_clock, seed, state=state)
    upcoming = sorted(scheduled, key=lambda e: e.trigger_sim_time)
    real_start = time_module.monotonic()
    stop_at = sim_clock.sim_start + timedelta(days=stop_after_days)

    for txn in gen:
        if txn.ts >= stop_at:
            break
        while upcoming and upcoming[0].trigger_sim_time <= txn.ts:
            scheduled_event = upcoming.pop(0)
            script = events.REGISTRY[scheduled_event.event_type]
            gt = script.apply(persona, state, scheduled_event.trigger_sim_time)
            print(f"[ground-truth] {gt.model_dump_json()}")
            _write_ground_truth(ground_truth_path, gt)

        sim_elapsed_days = (txn.ts - sim_clock.sim_start).total_seconds() / 86400.0
        target_real_offset = sim_elapsed_days * speed
        real_elapsed = time_module.monotonic() - real_start
        delay = target_real_offset - real_elapsed
        if delay > 0:
            await asyncio.sleep(delay)

        envelope = generator.to_envelope(txn)
        await _publish(redis_client, envelope)


async def _amain(args: argparse.Namespace) -> None:
    import redis.asyncio as aioredis

    redis_url = os.environ.get("REDIS_URL", DEFAULT_REDIS_URL)
    redis_client = aioredis.from_url(redis_url)

    cohort = personas.make_cohort(args.cohort, args.seed)
    print(f"Cohort of {len(cohort)} personas built (seed={args.seed}).")

    sim_start = datetime.combine(generator.DEFAULT_HISTORY_START, datetime.min.time())
    sim_clock = generator.SimClock(sim_start=sim_start)
    schedule = _schedule_life_events(cohort, sim_start, args.run_days, args.life_events, args.seed)
    ground_truth_path = OUT_DIR / "ground_truth.jsonl"

    try:
        tasks = [
            _run_persona_live(
                persona,
                args.seed,
                sim_clock,
                float(args.speed),
                redis_client,
                schedule.get(persona.id, []),
                ground_truth_path,
                float(args.run_days),
            )
            for persona in cohort
        ]
        await asyncio.gather(*tasks)
    finally:
        await redis_client.aclose()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sarathi synthetic-India transaction stream publisher."
    )
    parser.add_argument("--speed", type=int, default=5, help="Real seconds per simulated day.")
    parser.add_argument("--cohort", type=int, default=20, help="Number of personas to simulate.")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic cohort/stream seed.")
    parser.add_argument(
        "--months-history",
        type=int,
        default=6,
        help="Months of backfill history conceptually preceding the live run (see seed.py).",
    )
    parser.add_argument(
        "--run-days",
        type=int,
        default=30,
        help="Simulated days to run the live stream for.",
    )
    parser.add_argument(
        "--life-events",
        type=int,
        default=3,
        help="Number of personas to schedule a scripted life event for.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    asyncio.run(_amain(args))


if __name__ == "__main__":
    main()
