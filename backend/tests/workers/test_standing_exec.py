"""Standing-instruction execution: real debits, goal accounting, skips, idempotency."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.models.banking import Account, Transaction
from app.models.customer import Customer
from app.models.engagement import Notification
from app.models.enums import (
    AccountType,
    GoalStatus,
    StandingCadence,
    StandingPurpose,
    StandingStatus,
    TxnChannel,
    TxnDirection,
)
from app.models.goal import SavingsGoal
from app.models.standing import StandingInstruction
from app.services import goals, standing

RUPEE = 100
PAST = date(2020, 1, 1)


async def _customer_account(
    db: AsyncSession, *, balance_paise: int
) -> tuple[Customer, Account]:
    customer = Customer(full_name="Standing Persona")
    db.add(customer)
    await db.flush()
    account = Account(
        customer_id=customer.id, type=AccountType.SAVINGS, balance_paise=balance_paise
    )
    db.add(account)
    await db.flush()
    await db.commit()
    return customer, account


async def _add_instruction(
    db: AsyncSession,
    *,
    customer: Customer,
    account: Account,
    amount_paise: int,
    purpose: StandingPurpose = StandingPurpose.SAVINGS,
    goal_id: uuid.UUID | None = None,
    cadence: StandingCadence = StandingCadence.MONTHLY,
    next_run_date: date = PAST,
    status: StandingStatus = StandingStatus.ACTIVE,
) -> StandingInstruction:
    si = StandingInstruction(
        customer_id=customer.id,
        from_account_id=account.id,
        purpose=purpose,
        goal_id=goal_id,
        amount_paise=amount_paise,
        cadence=cadence,
        next_run_date=next_run_date,
        status=status,
    )
    db.add(si)
    await db.flush()
    await db.commit()
    return si


async def test_due_instruction_posts_real_debit(db: AsyncSession) -> None:
    customer, account = await _customer_account(db, balance_paise=20_000 * RUPEE)
    si = await _add_instruction(db, customer=customer, account=account, amount_paise=2_000 * RUPEE)

    executed = await standing.execute_due_instructions(db, get_redis())
    await db.commit()
    assert executed == 1

    refreshed_account = await db.get(Account, account.id)
    assert refreshed_account is not None
    assert refreshed_account.balance_paise == 18_000 * RUPEE

    txn = await db.scalar(sa.select(Transaction).where(Transaction.account_id == account.id))
    assert txn is not None
    assert txn.direction is TxnDirection.DEBIT
    assert txn.channel is TxnChannel.AUTO_DEBIT
    assert txn.merchant == "Sarathi Auto-Transfer"
    assert txn.category == "standing_instruction"

    refreshed = await db.get(StandingInstruction, si.id)
    assert refreshed is not None
    assert refreshed.runs_count == 1
    assert refreshed.last_run_at is not None
    assert refreshed.next_run_date == date(2020, 2, 1)  # advanced one month


async def test_goal_purpose_decrements_baseline_keeping_progress(db: AsyncSession) -> None:
    customer, account = await _customer_account(db, balance_paise=20_000 * RUPEE)
    goal = await goals.create_goal(
        db, customer_id=customer.id, name="Europe", target_paise=10_000 * RUPEE
    )
    await db.commit()
    assert goal.baseline_paise == 20_000 * RUPEE  # captured at creation

    balance_before = 20_000 * RUPEE
    progress_before, _ = goals.compute_progress(goal, balance_before)

    si = await _add_instruction(
        db,
        customer=customer,
        account=account,
        amount_paise=2_000 * RUPEE,
        purpose=StandingPurpose.GOAL,
        goal_id=goal.id,
    )

    executed = await standing.execute_due_instructions(db, get_redis())
    await db.commit()
    assert executed == 1

    refreshed_goal = await db.get(SavingsGoal, goal.id)
    refreshed_account = await db.get(Account, account.id)
    assert refreshed_goal is not None and refreshed_account is not None
    # Baseline dropped by the transfer amount (envelope accounting).
    assert refreshed_goal.baseline_paise == 18_000 * RUPEE
    # Net effect: progress is unchanged by the transfer (cash moved, not lost).
    progress_after, _ = goals.compute_progress(refreshed_goal, refreshed_account.balance_paise)
    assert progress_after == progress_before

    refreshed_si = await db.get(StandingInstruction, si.id)
    assert refreshed_si is not None and refreshed_si.runs_count == 1


async def test_insufficient_balance_skips_and_notifies(db: AsyncSession) -> None:
    # Balance leaves less than the Rs 1,000 floor buffer after the transfer.
    customer, account = await _customer_account(db, balance_paise=2_500 * RUPEE)
    si = await _add_instruction(db, customer=customer, account=account, amount_paise=2_000 * RUPEE)

    executed = await standing.execute_due_instructions(db, get_redis())
    await db.commit()
    assert executed == 0

    # No debit posted, balance untouched.
    refreshed_account = await db.get(Account, account.id)
    assert refreshed_account is not None and refreshed_account.balance_paise == 2_500 * RUPEE
    txns = (
        await db.scalars(sa.select(Transaction).where(Transaction.account_id == account.id))
    ).all()
    assert list(txns) == []

    note = await db.scalar(
        sa.select(Notification).where(Notification.customer_id == customer.id)
    )
    assert note is not None
    assert "too low" in note.title.lower()

    # Skipped, but next_run_date still advances (no retry until next cycle).
    refreshed = await db.get(StandingInstruction, si.id)
    assert refreshed is not None
    assert refreshed.runs_count == 0
    assert refreshed.next_run_date == date(2020, 2, 1)


async def test_idempotency_lock_prevents_double_post(db: AsyncSession) -> None:
    customer, account = await _customer_account(db, balance_paise=20_000 * RUPEE)
    si = await _add_instruction(db, customer=customer, account=account, amount_paise=2_000 * RUPEE)

    # Pre-set the per-(instruction, due-date) lock, simulating a prior/overlapping tick.
    redis = get_redis()
    await redis.set(standing._idempotency_key(si.id, PAST), "1")

    executed = await standing.execute_due_instructions(db, redis)
    await db.commit()
    assert executed == 0

    refreshed_account = await db.get(Account, account.id)
    assert refreshed_account is not None and refreshed_account.balance_paise == 20_000 * RUPEE
    refreshed = await db.get(StandingInstruction, si.id)
    assert refreshed is not None and refreshed.next_run_date == PAST  # untouched


async def test_paused_instruction_not_run(db: AsyncSession) -> None:
    customer, account = await _customer_account(db, balance_paise=20_000 * RUPEE)
    await _add_instruction(
        db,
        customer=customer,
        account=account,
        amount_paise=2_000 * RUPEE,
        status=StandingStatus.PAUSED,
    )
    executed = await standing.execute_due_instructions(db, get_redis())
    await db.commit()
    assert executed == 0


async def test_per_tick_cap(db: AsyncSession, monkeypatch: Any) -> None:
    monkeypatch.setattr(standing, "MAX_PER_TICK", 2)
    customer, account = await _customer_account(db, balance_paise=100_000 * RUPEE)
    for _ in range(3):
        await _add_instruction(
            db, customer=customer, account=account, amount_paise=1_000 * RUPEE
        )

    executed = await standing.execute_due_instructions(db, get_redis())
    await db.commit()
    assert executed == 2  # capped, third stays due for the next tick

    still_due = (
        await db.scalars(
            sa.select(StandingInstruction).where(
                StandingInstruction.next_run_date <= PAST,
                StandingInstruction.status == StandingStatus.ACTIVE,
            )
        )
    ).all()
    assert len(still_due) == 1


async def test_achieved_goal_completes_instruction(db: AsyncSession) -> None:
    customer, account = await _customer_account(db, balance_paise=20_000 * RUPEE)
    goal = SavingsGoal(
        customer_id=customer.id,
        name="Done",
        target_paise=1 * RUPEE,
        baseline_paise=0,
        status=GoalStatus.ACHIEVED,
        achieved_at=datetime.now(UTC),
    )
    db.add(goal)
    await db.flush()
    si = await _add_instruction(
        db,
        customer=customer,
        account=account,
        amount_paise=2_000 * RUPEE,
        purpose=StandingPurpose.GOAL,
        goal_id=goal.id,
    )

    executed = await standing.execute_due_instructions(db, get_redis())
    await db.commit()
    assert executed == 0  # no debit for a completed goal

    refreshed = await db.get(StandingInstruction, si.id)
    assert refreshed is not None
    assert refreshed.status is StandingStatus.COMPLETED
