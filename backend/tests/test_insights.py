"""Pure aggregation tests for `app.services.insights` - no DB, no LLM.

Every helper here (`bucket_monthly_breakdown`, `bucket_top_category_change`,
`bucket_largest_txn`, `bucket_recurring_merchants`) takes a plain list of
`TxnRow` dicts and a fixed `now`, so every case is a crafted fixture with a
deterministic, reproducible answer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.insights import (
    TxnRow,
    bucket_largest_txn,
    bucket_monthly_breakdown,
    bucket_recurring_merchants,
    bucket_top_category_change,
)

_NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


def _txn(
    ts: datetime,
    *,
    amount: int,
    direction: str,
    category: str | None = None,
    merchant: str | None = None,
) -> TxnRow:
    return {
        "ts": ts,
        "amount_paise": amount,
        "direction": direction,
        "category": category,
        "merchant": merchant,
    }


# ---------------------------------------------------------------------------
# bucket_monthly_breakdown
# ---------------------------------------------------------------------------


def test_empty_account_returns_honest_zeros() -> None:
    result = bucket_monthly_breakdown([], months=3, now=_NOW)
    months = result["months"]
    assert [m["month"] for m in months] == ["2026-07", "2026-06", "2026-05"]
    for m in months:
        assert m["total_in_paise"] == 0
        assert m["total_out_paise"] == 0
        assert m["by_category"] == []
    assert result["note"] is None


def test_category_breakdown_share_and_sort_desc() -> None:
    txns = [
        _txn(_NOW, amount=300_00, direction="debit", category="groceries"),
        _txn(_NOW, amount=300_00, direction="debit", category="groceries"),
        _txn(_NOW, amount=400_00, direction="debit", category="transport"),
        _txn(_NOW, amount=5000_00, direction="credit", category="salary"),
    ]
    result = bucket_monthly_breakdown(txns, months=1, now=_NOW)
    current = result["months"][0]
    assert current["month"] == "2026-07"
    assert current["total_in_paise"] == 5000_00
    assert current["total_out_paise"] == 1000_00

    by_category = current["by_category"]
    assert [c["category"] for c in by_category] == ["groceries", "transport"]
    assert by_category[0]["amount_paise"] == 600_00
    assert by_category[0]["share_pct"] == 60.0
    assert by_category[0]["txn_count"] == 2
    assert by_category[1]["amount_paise"] == 400_00
    assert by_category[1]["share_pct"] == 40.0
    assert by_category[1]["txn_count"] == 1


def test_month_bucketing_respects_utc_calendar_boundary() -> None:
    """A txn one second before midnight UTC on the 30th lands in June, the very
    next second (00:00:00 on the 1st) lands in July - even though both are the
    same "day" in a non-UTC timezone."""
    june_side = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)
    july_side = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)
    txns = [
        _txn(june_side, amount=100_00, direction="debit", category="groceries"),
        _txn(july_side, amount=200_00, direction="debit", category="groceries"),
    ]
    result = bucket_monthly_breakdown(txns, months=2, now=_NOW)
    by_month = {m["month"]: m for m in result["months"]}
    assert by_month["2026-07"]["total_out_paise"] == 200_00
    assert by_month["2026-06"]["total_out_paise"] == 100_00


def test_uncategorized_debit_falls_back_to_placeholder_category() -> None:
    txns = [_txn(_NOW, amount=50_00, direction="debit", category=None)]
    result = bucket_monthly_breakdown(txns, months=1, now=_NOW)
    by_category = result["months"][0]["by_category"]
    assert by_category == [
        {"category": "uncategorized", "amount_paise": 50_00, "share_pct": 100.0, "txn_count": 1}
    ]


def test_spending_spike_note_fires_over_threshold() -> None:
    prev_month = _NOW - timedelta(days=31)
    txns = [
        _txn(prev_month, amount=1000_00, direction="debit", category="groceries"),
        _txn(_NOW, amount=1400_00, direction="debit", category="groceries"),  # +40%
    ]
    result = bucket_monthly_breakdown(txns, months=2, now=_NOW)
    assert result["note"] is not None
    assert "up 40%" in result["note"]
    assert "July 2026" in result["note"]
    assert "June 2026" in result["note"]


def test_spending_spike_note_silent_under_threshold() -> None:
    prev_month = _NOW - timedelta(days=31)
    txns = [
        _txn(prev_month, amount=1000_00, direction="debit", category="groceries"),
        _txn(_NOW, amount=1200_00, direction="debit", category="groceries"),  # +20%, below 30%
    ]
    result = bucket_monthly_breakdown(txns, months=2, now=_NOW)
    assert result["note"] is None


def test_spending_spike_note_silent_with_zero_baseline() -> None:
    # New spend with nothing the prior month to compare against - not a "spike".
    txns = [_txn(_NOW, amount=500_00, direction="debit", category="groceries")]
    result = bucket_monthly_breakdown(txns, months=2, now=_NOW)
    assert result["note"] is None


def test_months_param_is_clamped_to_valid_range() -> None:
    assert len(bucket_monthly_breakdown([], months=0, now=_NOW)["months"]) == 1
    assert len(bucket_monthly_breakdown([], months=99, now=_NOW)["months"]) == 12


# ---------------------------------------------------------------------------
# bucket_top_category_change
# ---------------------------------------------------------------------------


def test_top_category_change_picks_largest_absolute_delta() -> None:
    prev_month = _NOW - timedelta(days=31)
    txns = [
        # groceries: 500 -> 700, delta +200
        _txn(prev_month, amount=500_00, direction="debit", category="groceries"),
        _txn(_NOW, amount=700_00, direction="debit", category="groceries"),
        # transport: 100 -> 2000, delta +1900 (the biggest mover)
        _txn(prev_month, amount=100_00, direction="debit", category="transport"),
        _txn(_NOW, amount=2000_00, direction="debit", category="transport"),
    ]
    change = bucket_top_category_change(txns, now=_NOW)
    assert change is not None
    assert change["category"] == "transport"
    assert change["prev_paise"] == 100_00
    assert change["curr_paise"] == 2000_00
    assert change["delta_pct"] == 1900.0


def test_top_category_change_new_category_has_null_delta_pct() -> None:
    txns = [_txn(_NOW, amount=300_00, direction="debit", category="entertainment")]
    change = bucket_top_category_change(txns, now=_NOW)
    assert change is not None
    assert change["category"] == "entertainment"
    assert change["prev_paise"] == 0
    assert change["delta_pct"] is None


def test_top_category_change_none_when_no_debits() -> None:
    assert bucket_top_category_change([], now=_NOW) is None


# ---------------------------------------------------------------------------
# bucket_largest_txn
# ---------------------------------------------------------------------------


def test_largest_txn_ignores_credits_and_outside_window() -> None:
    too_old = _NOW - timedelta(days=45)
    txns = [
        _txn(_NOW, amount=50_000_00, direction="credit", category="salary"),  # bigger, but credit
        _txn(too_old, amount=10_000_00, direction="debit", category="shopping"),  # outside 30d
        _txn(_NOW - timedelta(days=2), amount=3_000_00, direction="debit",
             category="shopping", merchant="Amazon"),
    ]
    largest = bucket_largest_txn(txns, now=_NOW)
    assert largest is not None
    assert largest["amount_paise"] == 3_000_00
    assert largest["merchant"] == "Amazon"


def test_largest_txn_none_when_no_recent_debits() -> None:
    assert bucket_largest_txn([], now=_NOW) is None


# ---------------------------------------------------------------------------
# bucket_recurring_merchants
# ---------------------------------------------------------------------------


def test_recurring_merchants_filters_by_monthly_average() -> None:
    txns = []
    # Netflix: 9 debits over 90 days = 3/mo avg -> included.
    for i in range(9):
        txns.append(
            _txn(
                _NOW - timedelta(days=i * 10), amount=500_00,
                direction="debit", merchant="Netflix",
            )
        )
    # Occasional cafe: 5 debits over 90 days ~= 1.67/mo avg -> excluded.
    for i in range(5):
        txns.append(
            _txn(_NOW - timedelta(days=i * 15), amount=200_00, direction="debit", merchant="Cafe")
        )
    recurring = bucket_recurring_merchants(txns, now=_NOW)
    merchants = [r["merchant"] for r in recurring]
    assert "Netflix" in merchants
    assert "Cafe" not in merchants
    netflix = next(r for r in recurring if r["merchant"] == "Netflix")
    assert netflix["count"] == 9
    assert netflix["monthly_avg_paise"] == round(9 * 500_00 / 3.0)


def test_recurring_merchants_excludes_credits_and_missing_merchant() -> None:
    txns = [
        _txn(_NOW, amount=1000_00, direction="credit", merchant="Employer"),
        _txn(_NOW, amount=100_00, direction="debit", merchant=None),
    ]
    assert bucket_recurring_merchants(txns, now=_NOW) == []
