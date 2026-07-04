"""Deterministic, pure prefilter rules over a customer's recent transaction window.

Cheap and fully unit-testable (no DB, no LLM) - this is the gate that decides
whether an incoming ``txn.events`` entry is *interesting* enough to spend an
agent run on. ``app.workers.event_consumer`` calls :func:`evaluate_rules` with the
customer's trailing transaction history (oldest→newest, excluding the new
transaction) plus the new transaction itself, and gets back every rule that fired
so it can (subject to cooldown) call ``run_event_trigger`` once per matched rule.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, TypedDict


class TxnLike(TypedDict, total=False):
    """The subset of a transaction's fields every rule needs."""

    ts: datetime
    amount_paise: int
    direction: str  # "credit" | "debit"
    channel: str
    category: str | None
    merchant: str | None
    balance_after_paise: int


@dataclass(frozen=True, slots=True)
class RuleMatch:
    """One prefilter rule firing: a stable ``rule`` name (used as the cooldown key),
    a crisp human-readable summary (fed to ``run_event_trigger``), and structured
    evidence for tracing/debugging."""

    rule: str
    event_summary: str
    evidence: dict[str, Any]


_INCOME_CATEGORIES = frozenset(
    {"salary", "pension", "business_inflow", "gig_payout", "pocket_money", "household_allowance"}
)

_SALARY_CHANGE_PCT = 0.25
_SALARY_WINDOW_DAYS = 180

_RECURRING_GROUPS: dict[str, frozenset[str]] = {
    "baby": frozenset({"pharmacy", "baby_essentials"}),
    "home": frozenset({"builder_payment", "home_loan_emi"}),
    "wedding": frozenset({"jewellery", "wedding_catering", "venue_booking"}),
}
_RECURRING_WINDOW_DAYS = 45
_RECURRING_MIN_COUNT = 2

_DRAIN_WINDOW_DAYS = 7
_DRAIN_OUTFLOW_FRACTION = 0.6

_DORMANCY_WINDOW_DAYS = 30

_WINDFALL_MULTIPLE = 3.0


def _in_window(rows: list[TxnLike], now: datetime, days: int) -> list[TxnLike]:
    cutoff = now - timedelta(days=days)
    return [r for r in rows if cutoff <= r["ts"] <= now]


def check_salary_change(history: list[TxnLike], new_txn: TxnLike) -> RuleMatch | None:
    """Salary/pension/etc. credit that moved >=25% vs the trailing median."""
    is_income_credit = (
        new_txn["direction"] == "credit" and (new_txn.get("category") or "") in _INCOME_CATEGORIES
    )
    if not is_income_credit:
        return None
    window = _in_window(history, new_txn["ts"], _SALARY_WINDOW_DAYS)
    prior_income = [
        r["amount_paise"]
        for r in window
        if r["direction"] == "credit" and (r.get("category") or "") in _INCOME_CATEGORIES
    ]
    if not prior_income:
        return None
    median = statistics.median(prior_income)
    if median <= 0:
        return None
    delta = (new_txn["amount_paise"] - median) / median
    if abs(delta) < _SALARY_CHANGE_PCT:
        return None
    direction = "increase" if delta > 0 else "decrease"
    return RuleMatch(
        rule="salary_change",
        event_summary=(
            f"Income {direction} of {delta:+.0%} vs trailing median income "
            f"(new credit {new_txn['amount_paise']} paise, median {int(median)} paise)"
        ),
        evidence={
            "new_amount_paise": new_txn["amount_paise"],
            "median_paise": int(median),
            "delta_pct": round(delta, 3),
        },
    )


def check_recurring_category(history: list[TxnLike], new_txn: TxnLike) -> RuleMatch | None:
    """A new recurring spend pattern in a life-event-linked category group."""
    category = new_txn.get("category") or ""
    group = next((g for g, cats in _RECURRING_GROUPS.items() if category in cats), None)
    if group is None:
        return None
    cats = _RECURRING_GROUPS[group]
    window = _in_window(history, new_txn["ts"], _RECURRING_WINDOW_DAYS)
    count = sum(1 for r in window if (r.get("category") or "") in cats) + 1  # +1 for new_txn
    if count < _RECURRING_MIN_COUNT:
        return None
    return RuleMatch(
        rule=f"recurring_category_{group}",
        event_summary=(
            f"Recurring '{group}'-linked spend detected "
            f"({count} transactions in the last {_RECURRING_WINDOW_DAYS} days)"
        ),
        evidence={"group": group, "count": count, "window_days": _RECURRING_WINDOW_DAYS},
    )


def check_balance_drain(history: list[TxnLike], new_txn: TxnLike) -> RuleMatch | None:
    """Churn candidate: >60% of the account's balance drained via outflow in 7 days."""
    window = _in_window(history, new_txn["ts"], _DRAIN_WINDOW_DAYS)
    combined = sorted([*window, new_txn], key=lambda r: r["ts"])
    if not combined:
        return None
    first = combined[0]
    first_after = first.get("balance_after_paise")
    if first_after is None:
        return None
    start_balance = (
        first_after + first["amount_paise"]
        if first["direction"] == "debit"
        else first_after - first["amount_paise"]
    )
    if start_balance <= 0:
        return None
    outflow = sum(r["amount_paise"] for r in combined if r["direction"] == "debit")
    fraction = outflow / start_balance
    if fraction < _DRAIN_OUTFLOW_FRACTION:
        return None
    return RuleMatch(
        rule="balance_drain",
        event_summary=(
            f"{fraction:.0%} of balance drained via outflow over the last {_DRAIN_WINDOW_DAYS} days"
        ),
        evidence={
            "outflow_paise": outflow,
            "start_balance_paise": start_balance,
            "fraction": round(fraction, 3),
        },
    )


def check_dormancy(
    history: list[TxnLike], new_txn: TxnLike, *, upi_active: bool
) -> RuleMatch | None:
    """Adoption candidate: no UPI activity in 30 days despite an UPI-active profile."""
    if not upi_active:
        return None
    window = _in_window(history, new_txn["ts"], _DORMANCY_WINDOW_DAYS)
    combined = [*window, new_txn]
    if any(r["channel"] == "upi" for r in combined):
        return None
    return RuleMatch(
        rule="dormancy",
        event_summary=(
            f"No UPI activity in {_DORMANCY_WINDOW_DAYS} days despite a UPI-active profile"
        ),
        evidence={"window_days": _DORMANCY_WINDOW_DAYS},
    )


def check_windfall(history: list[TxnLike], new_txn: TxnLike) -> RuleMatch | None:
    """A one-off credit >= 3x the customer's trailing median income."""
    if new_txn["direction"] != "credit":
        return None
    window = _in_window(history, new_txn["ts"], _SALARY_WINDOW_DAYS)
    salaries = [
        r["amount_paise"]
        for r in window
        if r["direction"] == "credit" and (r.get("category") or "") in _INCOME_CATEGORIES
    ]
    if not salaries:
        return None
    median_salary = statistics.median(salaries)
    if median_salary <= 0 or new_txn["amount_paise"] < _WINDFALL_MULTIPLE * median_salary:
        return None
    return RuleMatch(
        rule="windfall",
        event_summary=(
            f"Windfall credit of {new_txn['amount_paise']} paise "
            f"(>= {_WINDFALL_MULTIPLE:g}x trailing median income of {int(median_salary)} paise)"
        ),
        evidence={
            "amount_paise": new_txn["amount_paise"],
            "median_income_paise": int(median_salary),
        },
    )


_AMOUNT_RULES = (check_salary_change, check_recurring_category, check_balance_drain, check_windfall)
"""Rules evaluated from transaction data alone (dormancy additionally needs the
customer's `upi_active` persona flag, so it is run separately in :func:`evaluate_rules`)."""


def evaluate_rules(
    history: list[TxnLike], new_txn: TxnLike, *, upi_active: bool
) -> list[RuleMatch]:
    """Run every deterministic prefilter rule; return every rule that matched.

    ``history`` must be the customer's transactions *excluding* ``new_txn``, in any
    order (each rule windows and sorts internally).
    """
    matches = [m for fn in _AMOUNT_RULES if (m := fn(history, new_txn)) is not None]
    dormancy = check_dormancy(history, new_txn, upi_active=upi_active)
    if dormancy is not None:
        matches.append(dormancy)
    return matches
