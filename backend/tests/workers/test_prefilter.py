"""Unit tests for the deterministic event-consumer prefilter rules.

Pure functions over plain dicts - no DB, no LLM, no event loop needed.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.workers.prefilter import (
    TxnLike,
    check_balance_drain,
    check_dormancy,
    check_recurring_category,
    check_salary_change,
    check_windfall,
    evaluate_rules,
)

NOW = datetime(2026, 6, 1, 9, 0, 0)


def _txn(
    *,
    days_ago: float = 0,
    amount_paise: int = 100_00,
    direction: str = "debit",
    channel: str = "upi",
    category: str | None = "groceries",
    merchant: str | None = "Test Merchant",
    balance_after_paise: int = 10_000_00,
) -> TxnLike:
    return TxnLike(
        ts=NOW - timedelta(days=days_ago),
        amount_paise=amount_paise,
        direction=direction,
        channel=channel,
        category=category,
        merchant=merchant,
        balance_after_paise=balance_after_paise,
    )


# ---------------------------------------------------------------------------
# salary_change
# ---------------------------------------------------------------------------


def test_salary_change_fires_on_large_increase() -> None:
    history = [
        _txn(days_ago=90, amount_paise=50_000_00, direction="credit", category="salary"),
        _txn(days_ago=60, amount_paise=50_000_00, direction="credit", category="salary"),
        _txn(days_ago=30, amount_paise=50_000_00, direction="credit", category="salary"),
    ]
    new_txn = _txn(days_ago=0, amount_paise=70_000_00, direction="credit", category="salary")
    match = check_salary_change(history, new_txn)
    assert match is not None
    assert match.rule == "salary_change"
    assert match.evidence["delta_pct"] > 0


def test_salary_change_none_below_threshold() -> None:
    history = [_txn(days_ago=30, amount_paise=50_000_00, direction="credit", category="salary")]
    new_txn = _txn(days_ago=0, amount_paise=52_000_00, direction="credit", category="salary")
    assert check_salary_change(history, new_txn) is None


def test_salary_change_ignores_non_income_category() -> None:
    history = [_txn(days_ago=30, amount_paise=50_000_00, direction="credit", category="salary")]
    new_txn = _txn(days_ago=0, amount_paise=200_000_00, direction="credit", category="bonus")
    assert check_salary_change(history, new_txn) is None


def test_salary_change_ignores_debits() -> None:
    history = [_txn(days_ago=30, amount_paise=50_000_00, direction="credit", category="salary")]
    new_txn = _txn(days_ago=0, amount_paise=50_000_00, direction="debit", category="salary")
    assert check_salary_change(history, new_txn) is None


# ---------------------------------------------------------------------------
# recurring_category
# ---------------------------------------------------------------------------


def test_recurring_category_fires_on_second_occurrence() -> None:
    history = [_txn(days_ago=10, category="pharmacy")]
    new_txn = _txn(days_ago=0, category="baby_essentials")
    match = check_recurring_category(history, new_txn)
    assert match is not None
    assert match.rule == "recurring_category_baby"
    assert match.evidence["count"] == 2


def test_recurring_category_none_on_first_occurrence() -> None:
    new_txn = _txn(days_ago=0, category="pharmacy")
    assert check_recurring_category([], new_txn) is None


def test_recurring_category_none_for_unrelated_category() -> None:
    new_txn = _txn(days_ago=0, category="groceries")
    assert check_recurring_category([], new_txn) is None


def test_recurring_category_ignores_out_of_window_occurrences() -> None:
    history = [_txn(days_ago=200, category="pharmacy")]  # outside the 45d window
    new_txn = _txn(days_ago=0, category="pharmacy")
    assert check_recurring_category(history, new_txn) is None


# ---------------------------------------------------------------------------
# balance_drain
# ---------------------------------------------------------------------------


def test_balance_drain_fires_on_large_7d_outflow() -> None:
    # Balance was 1,000,00 paise before the first drain debit in the window.
    history = [
        _txn(days_ago=5, amount_paise=300_00, direction="debit", balance_after_paise=700_00),
    ]
    new_txn = _txn(days_ago=0, amount_paise=400_00, direction="debit", balance_after_paise=300_00)
    match = check_balance_drain(history, new_txn)
    assert match is not None
    assert match.rule == "balance_drain"
    assert match.evidence["fraction"] >= 0.6


def test_balance_drain_none_for_small_outflow() -> None:
    history = [
        _txn(days_ago=5, amount_paise=50_00, direction="debit", balance_after_paise=950_00),
    ]
    new_txn = _txn(days_ago=0, amount_paise=50_00, direction="debit", balance_after_paise=900_00)
    assert check_balance_drain(history, new_txn) is None


# ---------------------------------------------------------------------------
# dormancy
# ---------------------------------------------------------------------------


def test_dormancy_fires_when_no_upi_and_active_profile() -> None:
    history = [_txn(days_ago=10, channel="neft", category="rent")]
    new_txn = _txn(days_ago=0, channel="neft", category="electricity")
    match = check_dormancy(history, new_txn, upi_active=True)
    assert match is not None
    assert match.rule == "dormancy"


def test_dormancy_none_when_not_upi_active_persona() -> None:
    history = [_txn(days_ago=10, channel="neft")]
    new_txn = _txn(days_ago=0, channel="neft")
    assert check_dormancy(history, new_txn, upi_active=False) is None


def test_dormancy_none_when_upi_seen_in_window() -> None:
    history = [_txn(days_ago=10, channel="upi")]
    new_txn = _txn(days_ago=0, channel="neft")
    assert check_dormancy(history, new_txn, upi_active=True) is None


# ---------------------------------------------------------------------------
# windfall
# ---------------------------------------------------------------------------


def test_windfall_fires_on_large_multiple_of_median_income() -> None:
    history = [_txn(days_ago=30, amount_paise=50_000_00, direction="credit", category="salary")]
    new_txn = _txn(days_ago=0, amount_paise=200_000_00, direction="credit", category="bonus")
    match = check_windfall(history, new_txn)
    assert match is not None
    assert match.rule == "windfall"


def test_windfall_none_below_multiple() -> None:
    history = [_txn(days_ago=30, amount_paise=50_000_00, direction="credit", category="salary")]
    new_txn = _txn(days_ago=0, amount_paise=60_000_00, direction="credit", category="bonus")
    assert check_windfall(history, new_txn) is None


# ---------------------------------------------------------------------------
# evaluate_rules aggregation
# ---------------------------------------------------------------------------


def test_evaluate_rules_returns_every_match() -> None:
    history: list[TxnLike] = []
    # A windfall credit that is also a salary-category credit fires both
    # salary_change (huge jump vs an empty trailing median falls through, since
    # median needs at least one prior income credit) - so seed one prior salary.
    history.append(_txn(days_ago=30, amount_paise=50_000_00, direction="credit", category="salary"))
    new_txn = _txn(days_ago=0, amount_paise=300_000_00, direction="credit", category="salary")
    matches = evaluate_rules(history, new_txn, upi_active=False)
    rules = {m.rule for m in matches}
    assert "salary_change" in rules
    assert "windfall" in rules
    assert "dormancy" not in rules  # upi_active=False


def test_evaluate_rules_empty_when_nothing_matches() -> None:
    new_txn = _txn(days_ago=0, amount_paise=100_00, direction="debit", category="chai_canteen")
    assert evaluate_rules([], new_txn, upi_active=False) == []
