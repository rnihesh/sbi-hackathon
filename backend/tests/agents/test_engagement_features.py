"""Engagement feature-extraction tests (deterministic, pre-LLM)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.agents.engagement import extract_features, feature_churn_score

_BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _txn(day: int, *, direction: str, category: str, amount: int, balance: int,
         merchant: str | None = None, channel: str = "neft") -> dict[str, object]:
    return {
        "ts": _BASE + timedelta(days=day),
        "amount_paise": amount,
        "direction": direction,
        "channel": channel,
        "merchant": merchant,
        "category": category,
        "balance_after_paise": balance,
    }


def test_detects_salary_and_hike() -> None:
    txns = [
        _txn(0, direction="credit", category="salary", amount=50_000_00, balance=50_000_00,
             merchant="Acme Corp"),
        _txn(30, direction="credit", category="salary", amount=70_000_00, balance=120_000_00,
             merchant="Acme Corp"),
    ]
    features = extract_features(txns, days=60)
    assert features["salary"]["detected"] is True
    assert features["salary"]["source"] == "Acme Corp"
    assert features["salary"]["direction"] == "up"
    assert features["salary"]["change_pct"] >= 0.15


def test_recurring_merchants_and_balance_trend() -> None:
    txns = [
        _txn(i, direction="debit", category="food_delivery", amount=300_00,
             balance=100_000_00 - i * 300_00, merchant="Swiggy", channel="upi")
        for i in range(4)
    ]
    features = extract_features(txns, days=30)
    merchants = {m["merchant"] for m in features["recurring_merchants"]}
    assert "Swiggy" in merchants
    assert features["balance_trend"]["direction"] == "down"
    assert features["upi_txn_count"] == 4


def test_windfall_detected_as_large_credit() -> None:
    txns = [
        _txn(0, direction="credit", category="salary", amount=50_000_00, balance=50_000_00,
             merchant="Acme"),
        _txn(10, direction="credit", category="bonus", amount=200_000_00, balance=250_000_00,
             merchant="Acme Bonus"),
    ]
    features = extract_features(txns, days=30)
    assert any(c["category"] == "bonus" for c in features["large_credits"])


def test_feature_churn_score_high_for_multiple_risk_signals() -> None:
    features = {
        "salary": {"detected": False, "direction": None},
        "balance_trend": {"direction": "down", "change_paise": -90_000, "start_paise": 100_000},
        "balance_drain_present": True,
        "upi_txn_count": 0,
    }
    score = feature_churn_score(features)
    assert score >= 0.9  # no salary (.3) + big drop (.3) + drain (.25) + no upi (.15) → capped 1.0


def test_feature_churn_score_low_for_healthy_customer() -> None:
    features = {
        "salary": {"detected": True, "direction": "up"},
        "balance_trend": {"direction": "up", "change_paise": 50_000, "start_paise": 100_000},
        "balance_drain_present": False,
        "upi_txn_count": 25,
    }
    assert feature_churn_score(features) == 0.0
