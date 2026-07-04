from __future__ import annotations

import json
from pathlib import Path

from app.sim import seed


def test_build_seed_data_is_deterministic() -> None:
    cohort_a, txns_a, gt_a = seed.build_seed_data(
        cohort_size=10, seed=42, months=3, life_events_count=2
    )
    cohort_b, txns_b, gt_b = seed.build_seed_data(
        cohort_size=10, seed=42, months=3, life_events_count=2
    )

    assert [p.model_dump() for p in cohort_a] == [p.model_dump() for p in cohort_b]
    assert [t.model_dump() for t in txns_a] == [t.model_dump() for t in txns_b]
    assert [g.model_dump() for g in gt_a] == [g.model_dump() for g in gt_b]


def test_build_seed_data_applies_requested_number_of_life_events() -> None:
    _cohort, _txns, gt = seed.build_seed_data(
        cohort_size=10, seed=42, months=6, life_events_count=3
    )
    assert len(gt) == 3
    assert len({g.customer_id for g in gt}) == 3


def test_build_seed_data_never_goes_negative() -> None:
    _cohort, txns, _gt = seed.build_seed_data(cohort_size=15, seed=7, months=6, life_events_count=4)
    assert all(t.balance_after_paise >= 0 for t in txns)


def test_build_seed_data_zero_life_events() -> None:
    _cohort, _txns, gt = seed.build_seed_data(cohort_size=5, seed=1, months=2, life_events_count=0)
    assert gt == []


def test_main_writes_jsonl_files(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    seed.main(
        [
            "--cohort",
            "6",
            "--seed",
            "42",
            "--months",
            "2",
            "--life-events",
            "1",
            "--out-dir",
            str(out_dir),
        ]
    )

    personas_path = out_dir / "personas.jsonl"
    transactions_path = out_dir / "transactions.jsonl"
    ground_truth_path = out_dir / "ground_truth.jsonl"
    assert personas_path.exists()
    assert transactions_path.exists()
    assert ground_truth_path.exists()

    persona_rows = [json.loads(line) for line in personas_path.read_text().splitlines()]
    assert len(persona_rows) == 6
    assert {"id", "name", "archetype", "monthly_income_paise"} <= persona_rows[0].keys()

    txn_rows = [json.loads(line) for line in transactions_path.read_text().splitlines()]
    assert txn_rows
    assert {"event_id", "customer_id", "ts", "amount_paise", "balance_after_paise"} <= txn_rows[
        0
    ].keys()

    gt_rows = [json.loads(line) for line in ground_truth_path.read_text().splitlines()]
    assert len(gt_rows) == 1
