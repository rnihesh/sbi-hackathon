from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import orjson
import pytest

from app.sim import events, generator, runner
from app.sim.personas import make_cohort


def test_build_arg_parser_defaults() -> None:
    parser = runner.build_arg_parser()
    args = parser.parse_args([])
    assert args.speed == 5
    assert args.cohort == 20
    assert args.seed == 42
    assert args.months_history == 6
    assert args.life_events == 3


def test_build_arg_parser_overrides() -> None:
    parser = runner.build_arg_parser()
    args = parser.parse_args(
        [
            "--speed",
            "1",
            "--cohort",
            "5",
            "--seed",
            "7",
            "--months-history",
            "2",
            "--life-events",
            "0",
        ]
    )
    assert (args.speed, args.cohort, args.seed, args.months_history, args.life_events) == (
        1,
        5,
        7,
        2,
        0,
    )


def test_schedule_life_events_picks_k_distinct_personas_deterministically() -> None:
    cohort = make_cohort(20, seed=42)
    sim_start = datetime(2024, 1, 1)
    schedule_a = runner._schedule_life_events(cohort, sim_start, run_days=30, k=4, seed=42)
    schedule_b = runner._schedule_life_events(cohort, sim_start, run_days=30, k=4, seed=42)

    assert len(schedule_a) == 4
    assert schedule_a.keys() == schedule_b.keys()
    for pid in schedule_a:
        assert schedule_a[pid] == schedule_b[pid]
        for scheduled in schedule_a[pid]:
            assert sim_start <= scheduled.trigger_sim_time <= sim_start + timedelta(days=30)


def test_schedule_life_events_zero_or_no_cohort() -> None:
    cohort = make_cohort(5, seed=1)
    assert runner._schedule_life_events(cohort, datetime(2024, 1, 1), 10, 0, 1) == {}
    assert runner._schedule_life_events([], datetime(2024, 1, 1), 10, 3, 1) == {}


def test_schedule_life_events_caps_k_at_cohort_size() -> None:
    cohort = make_cohort(3, seed=1)
    schedule = runner._schedule_life_events(cohort, datetime(2024, 1, 1), 10, 100, seed=1)
    assert len(schedule) == 3


def test_write_ground_truth_appends_jsonl(tmp_path: Path) -> None:
    gt = events.GroundTruthEvent(
        customer_id="c1",
        type=events.LifeEventType.BONUS_WINDFALL,
        start_ts=datetime(2024, 1, 1),
        params={"amount_paise": 100},
    )
    path = tmp_path / "out" / "ground_truth.jsonl"
    runner._write_ground_truth(path, gt)
    runner._write_ground_truth(path, gt)

    lines = path.read_text().strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        row = orjson.loads(line)
        assert row["customer_id"] == "c1"
        assert row["type"] == "bonus_windfall"


class _FakeRedis:
    def __init__(self) -> None:
        self.added: list[tuple[str, dict[str, bytes]]] = []
        self.closed = False

    async def xadd(self, name: str, fields: dict[str, bytes]) -> str:
        self.added.append((name, fields))
        return "0-1"

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_run_persona_live_publishes_expected_envelopes(tmp_path: Path) -> None:
    cohort = make_cohort(3, seed=42)
    persona = cohort[0]
    sim_clock = generator.SimClock(sim_start=datetime(2024, 1, 1))
    fake_redis = _FakeRedis()

    await runner._run_persona_live(
        persona,
        seed=42,
        sim_clock=sim_clock,
        speed=0.0,  # no real-time delay -- test runs instantly
        redis_client=fake_redis,
        scheduled=[],
        ground_truth_path=tmp_path / "ground_truth.jsonl",
        stop_after_days=3.0,
    )

    assert fake_redis.added, "expected at least one published transaction"
    for stream_name, fields in fake_redis.added:
        assert stream_name == runner.STREAM_NAME
        envelope = orjson.loads(fields["data"])
        assert envelope["type"] == "transaction"
        assert envelope["customer_id"] == persona.id
        datetime.fromisoformat(envelope["ts"])


@pytest.mark.asyncio
async def test_run_persona_live_applies_scheduled_life_event(tmp_path: Path) -> None:
    cohort = make_cohort(3, seed=42)
    persona = cohort[0]
    sim_clock = generator.SimClock(sim_start=datetime(2024, 1, 1))
    fake_redis = _FakeRedis()
    gt_path = tmp_path / "ground_truth.jsonl"

    scheduled = [
        runner.ScheduledLifeEvent(
            persona_id=persona.id,
            event_type=events.LifeEventType.BONUS_WINDFALL,
            trigger_sim_time=sim_clock.sim_start + timedelta(days=1),
        )
    ]

    await runner._run_persona_live(
        persona,
        seed=42,
        sim_clock=sim_clock,
        speed=0.0,
        redis_client=fake_redis,
        scheduled=scheduled,
        ground_truth_path=gt_path,
        stop_after_days=5.0,
    )

    assert gt_path.exists()
    rows = [orjson.loads(line) for line in gt_path.read_text().strip().splitlines()]
    assert any(row["type"] == "bonus_windfall" for row in rows)

    bonus_envelopes = [orjson.loads(fields["data"]) for _, fields in fake_redis.added]
    assert any(e["payload"]["category"] == "bonus" for e in bonus_envelopes)
