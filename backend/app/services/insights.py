"""Spending insights - deterministic aggregation over real transactions.

No LLM anywhere in this module. ``monthly_breakdown`` and ``trends`` are the
DB-touching entry points (session + customer_id, real SQL over
``transactions``/``accounts``); each is a thin fetch that hands the rows to a
pure ``bucket_*`` helper below it. The pure helpers operate on plain
``TxnRow`` dicts and are unit-testable with crafted fixtures - no DB, no LLM,
no dependency on the sim engine.

All money is paise (integer). Percentages (``share_pct``, ``delta_pct``) are
0-100 scale floats, rounded to one decimal place, ready to render as "23.4%".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.banking import Account, Transaction

_MIN_MONTHS = 1
_MAX_MONTHS = 12
_RECURRING_WINDOW_DAYS = 90
_LARGEST_TXN_WINDOW_DAYS = 30
_SPIKE_THRESHOLD_PCT = 30.0
_RECURRING_MIN_MONTHLY_OCCURRENCES = 3.0


class TxnRow(TypedDict):
    """The subset of a transaction the pure aggregation helpers need."""

    ts: datetime
    amount_paise: int
    direction: str
    category: str | None
    merchant: str | None


# ---------------------------------------------------------------------------
# Calendar-month helpers (UTC-anchored, avoid Postgres session-timezone drift)
# ---------------------------------------------------------------------------


def _month_key(ts: datetime) -> str:
    """Format a UTC calendar-month bucket key, e.g. ``"2026-07"``."""
    return ts.astimezone(UTC).strftime("%Y-%m")


def _month_start(year: int, month: int) -> datetime:
    return datetime(year, month, 1, tzinfo=UTC)


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """Shift a (year, month) pair by ``delta`` calendar months."""
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _month_range(months: int, *, now: datetime) -> list[tuple[int, int]]:
    """Return ``months`` (year, month) tuples, newest first, ending at ``now``'s month."""
    clamped = max(_MIN_MONTHS, min(_MAX_MONTHS, months))
    return [_shift_month(now.year, now.month, -i) for i in range(clamped)]


def _humanize_month(key: str) -> str:
    return datetime.strptime(key, "%Y-%m").replace(tzinfo=UTC).strftime("%B %Y")


# ---------------------------------------------------------------------------
# Pure aggregation (unit-tested directly against crafted TxnRow fixtures)
# ---------------------------------------------------------------------------


def bucket_monthly_breakdown(
    txns: list[TxnRow], months: int, *, now: datetime
) -> dict[str, Any]:
    """Bucket ``txns`` into the last ``months`` UTC calendar months.

    Always returns exactly ``months`` buckets, newest first, even for months
    with zero activity - an empty account gets honest zeros, never missing
    keys. Also computes ``note`` (see :func:`_spending_spike_note`).
    """
    month_tuples = _month_range(months, now=now)
    wanted_keys = {f"{y:04d}-{m:02d}" for y, m in month_tuples}

    per_month: dict[str, list[TxnRow]] = {key: [] for key in wanted_keys}
    for t in txns:
        key = _month_key(t["ts"])
        bucket = per_month.get(key)
        if bucket is not None:
            bucket.append(t)

    result_months: list[dict[str, Any]] = []
    for year, month in month_tuples:
        key = f"{year:04d}-{month:02d}"
        rows = per_month[key]
        total_in = sum(r["amount_paise"] for r in rows if r["direction"] == "credit")
        total_out = sum(r["amount_paise"] for r in rows if r["direction"] == "debit")

        by_cat: dict[str, dict[str, int]] = {}
        for r in rows:
            if r["direction"] != "debit":
                continue
            cat = r["category"] or "uncategorized"
            entry = by_cat.setdefault(cat, {"amount_paise": 0, "txn_count": 0})
            entry["amount_paise"] += r["amount_paise"]
            entry["txn_count"] += 1

        by_category: list[dict[str, Any]] = [
            {
                "category": cat,
                "amount_paise": data["amount_paise"],
                "share_pct": round(data["amount_paise"] / total_out * 100, 1) if total_out else 0.0,
                "txn_count": data["txn_count"],
            }
            for cat, data in by_cat.items()
        ]
        by_category.sort(key=lambda c: (-int(c["amount_paise"]), str(c["category"])))

        result_months.append(
            {
                "month": key,
                "total_in_paise": total_in,
                "total_out_paise": total_out,
                "by_category": by_category,
            }
        )

    return {"months": result_months, "note": _spending_spike_note(result_months)}


def _spending_spike_note(months: list[dict[str, Any]]) -> str | None:
    """A factual "spending is up X%" note when the newest month's spend spikes.

    Only fires when there's a real previous month to compare against with
    nonzero spend (a zero baseline can't produce a meaningful percentage).
    """
    if len(months) < 2:
        return None
    curr, prev = months[0], months[1]
    prev_out, curr_out = int(prev["total_out_paise"]), int(curr["total_out_paise"])
    if prev_out <= 0:
        return None
    pct = (curr_out - prev_out) / prev_out * 100
    if pct <= _SPIKE_THRESHOLD_PCT:
        return None
    return (
        f"Spending in {_humanize_month(str(curr['month']))} is up {round(pct)}% vs "
        f"{_humanize_month(str(prev['month']))}."
    )


def bucket_top_category_change(txns: list[TxnRow], *, now: datetime) -> dict[str, Any] | None:
    """The debit category with the largest absolute paise swing, current vs previous month."""
    (cur_y, cur_m), (prev_y, prev_m) = _month_range(2, now=now)
    cur_key, prev_key = f"{cur_y:04d}-{cur_m:02d}", f"{prev_y:04d}-{prev_m:02d}"

    def _category_totals(key: str) -> dict[str, int]:
        totals: dict[str, int] = {}
        for t in txns:
            if t["direction"] != "debit" or _month_key(t["ts"]) != key:
                continue
            cat = t["category"] or "uncategorized"
            totals[cat] = totals.get(cat, 0) + t["amount_paise"]
        return totals

    curr_totals, prev_totals = _category_totals(cur_key), _category_totals(prev_key)
    categories = sorted(set(curr_totals) | set(prev_totals))
    if not categories:
        return None

    best: dict[str, Any] | None = None
    best_abs_delta = -1
    for cat in categories:
        curr_paise, prev_paise = curr_totals.get(cat, 0), prev_totals.get(cat, 0)
        delta = curr_paise - prev_paise
        if abs(delta) > best_abs_delta:
            best_abs_delta = abs(delta)
            delta_pct = round(delta / prev_paise * 100, 1) if prev_paise else None
            best = {
                "category": cat,
                "prev_paise": prev_paise,
                "curr_paise": curr_paise,
                "delta_pct": delta_pct,
            }
    return best


def bucket_largest_txn(txns: list[TxnRow], *, now: datetime) -> dict[str, Any] | None:
    """The single largest debit in the trailing 30 days."""
    cutoff = now - timedelta(days=_LARGEST_TXN_WINDOW_DAYS)
    candidates = [t for t in txns if t["direction"] == "debit" and t["ts"] >= cutoff]
    if not candidates:
        return None
    largest = max(candidates, key=lambda t: (t["amount_paise"], t["ts"]))
    return {
        "amount_paise": largest["amount_paise"],
        "merchant": largest["merchant"],
        "category": largest["category"],
        "ts": largest["ts"],
    }


def bucket_recurring_merchants(
    txns: list[TxnRow], *, window_days: int = _RECURRING_WINDOW_DAYS, now: datetime
) -> list[dict[str, Any]]:
    """Merchants billed >= 3x/month on average over the trailing window.

    Catches subscriptions, EMIs, rent - anything recurring enough to be worth
    surfacing as a predictable monthly cost.
    """
    cutoff = now - timedelta(days=window_days)
    months_in_window = window_days / 30.0

    per_merchant: dict[str, dict[str, int]] = {}
    for t in txns:
        merchant = t["merchant"]
        if t["direction"] != "debit" or not merchant or t["ts"] < cutoff:
            continue
        entry = per_merchant.setdefault(merchant, {"count": 0, "total_paise": 0})
        entry["count"] += 1
        entry["total_paise"] += t["amount_paise"]

    recurring: list[dict[str, Any]] = [
        {
            "merchant": merchant,
            "monthly_avg_paise": round(data["total_paise"] / months_in_window),
            "count": data["count"],
        }
        for merchant, data in per_merchant.items()
        if data["count"] / months_in_window >= _RECURRING_MIN_MONTHLY_OCCURRENCES
    ]
    recurring.sort(key=lambda r: (-int(r["monthly_avg_paise"]), str(r["merchant"])))
    return recurring


def bucket_trends(txns: list[TxnRow], *, now: datetime) -> dict[str, Any]:
    return {
        "top_category_change": bucket_top_category_change(txns, now=now),
        "largest_txn_30d": bucket_largest_txn(txns, now=now),
        "recurring": bucket_recurring_merchants(txns, now=now),
    }


# ---------------------------------------------------------------------------
# DB-touching entry points
# ---------------------------------------------------------------------------


async def _fetch_since(
    session: AsyncSession, customer_id: uuid.UUID, since: datetime
) -> list[TxnRow]:
    stmt = (
        sa.select(Transaction)
        .join(Account, Transaction.account_id == Account.id)
        .where(Account.customer_id == customer_id, Transaction.ts >= since)
        .order_by(Transaction.ts)
    )
    rows = (await session.scalars(stmt)).all()
    return [
        {
            "ts": t.ts,
            "amount_paise": t.amount_paise,
            "direction": t.direction.value,
            "category": t.category,
            "merchant": t.merchant,
        }
        for t in rows
    ]


async def monthly_breakdown(
    session: AsyncSession, customer_id: uuid.UUID, months: int = 3
) -> dict[str, Any]:
    """Real per-month in/out totals + category breakdown for a customer.

    Fetches every transaction since the start of the earliest requested month
    (one indexed query, joined on ``Account.customer_id``) and delegates the
    actual bucketing/aggregation to :func:`bucket_monthly_breakdown`.
    """
    now = datetime.now(UTC)
    clamped = max(_MIN_MONTHS, min(_MAX_MONTHS, months))
    earliest = _month_range(clamped, now=now)[-1]
    since = _month_start(*earliest)
    txns = await _fetch_since(session, customer_id, since)
    return bucket_monthly_breakdown(txns, clamped, now=now)


async def trends(session: AsyncSession, customer_id: uuid.UUID) -> dict[str, Any]:
    """Real trend signals: top category mover, largest recent expense, recurring merchants."""
    now = datetime.now(UTC)
    since_by_window = now - timedelta(days=max(_RECURRING_WINDOW_DAYS, _LARGEST_TXN_WINDOW_DAYS))
    prev_month_start = _month_start(*_shift_month(now.year, now.month, -1))
    since = min(since_by_window, prev_month_start)
    txns = await _fetch_since(session, customer_id, since)
    return bucket_trends(txns, now=now)
