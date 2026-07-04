"""Ledger service - a real, minimal core-banking ledger over the DB.

All amounts are in **paise** (integer) to avoid float money. Balance mutations
go through :func:`post_transaction`, which takes a row-level lock on the account
so concurrent posts stay consistent (no lost updates, no negative balances
unless explicitly allowed).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.banking import Account, Transaction
from app.models.enums import AccountStatus, AccountType, TxnChannel, TxnDirection


class LedgerError(Exception):
    """Raised on invalid ledger operations (unknown account, overdraft, etc.)."""


def _coerce_account_type(account_type: AccountType | str) -> AccountType:
    return account_type if isinstance(account_type, AccountType) else AccountType(account_type)


def _coerce_direction(direction: TxnDirection | str) -> TxnDirection:
    return direction if isinstance(direction, TxnDirection) else TxnDirection(direction)


def _coerce_channel(channel: TxnChannel | str) -> TxnChannel:
    return channel if isinstance(channel, TxnChannel) else TxnChannel(channel)


async def open_account(
    session: AsyncSession,
    *,
    customer_id: uuid.UUID,
    account_type: AccountType | str,
    initial_deposit_paise: int = 0,
    label: str | None = None,
) -> Account:
    """Open a new account for a customer, optionally seeding an opening deposit.

    The opening deposit (if any) is posted as a real ``CASH`` credit transaction
    so the account's history is internally consistent from the first rupee.
    """
    if initial_deposit_paise < 0:
        raise LedgerError("initial deposit cannot be negative")

    account = Account(
        customer_id=customer_id,
        type=_coerce_account_type(account_type),
        balance_paise=0,
        status=AccountStatus.ACTIVE,
        label=label,
    )
    session.add(account)
    await session.flush()  # assign account.id

    if initial_deposit_paise > 0:
        await post_transaction(
            session,
            account_id=account.id,
            amount_paise=initial_deposit_paise,
            direction=TxnDirection.CREDIT,
            channel=TxnChannel.CASH,
            description="Opening deposit",
            category="account_opening",
        )
    return account


async def get_account(session: AsyncSession, account_id: uuid.UUID) -> Account:
    account = await session.get(Account, account_id)
    if account is None:
        raise LedgerError(f"account {account_id} not found")
    return account


async def get_balance(session: AsyncSession, account_id: uuid.UUID) -> int:
    """Return an account's current balance in paise."""
    account = await get_account(session, account_id)
    return account.balance_paise


async def get_customer_balance(session: AsyncSession, customer_id: uuid.UUID) -> int:
    """Return the summed balance (paise) across a customer's non-closed accounts."""
    stmt = sa.select(sa.func.coalesce(sa.func.sum(Account.balance_paise), 0)).where(
        Account.customer_id == customer_id,
        Account.status != AccountStatus.CLOSED,
    )
    total = await session.scalar(stmt)
    return int(total or 0)


async def list_accounts(session: AsyncSession, customer_id: uuid.UUID) -> list[Account]:
    stmt = (
        sa.select(Account)
        .where(Account.customer_id == customer_id)
        .order_by(Account.created_at)
    )
    return list((await session.scalars(stmt)).all())


async def get_recent_transactions(
    session: AsyncSession,
    customer_id: uuid.UUID,
    days: int,
    *,
    limit: int | None = None,
) -> list[Transaction]:
    """Return a customer's transactions from the last ``days`` days, newest first."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    stmt = (
        sa.select(Transaction)
        .join(Account, Transaction.account_id == Account.id)
        .where(Account.customer_id == customer_id, Transaction.ts >= cutoff)
        .order_by(Transaction.ts.desc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list((await session.scalars(stmt)).all())


async def get_latest_transactions(
    session: AsyncSession, customer_id: uuid.UUID, *, limit: int = 20
) -> list[Transaction]:
    """Return a customer's most recent ``limit`` transactions, newest first.

    Unlike :func:`get_recent_transactions`, this has no day-window cutoff - it is
    "latest N", which is what a dashboard's recent-activity list wants (sim seed
    data is anchored to a fixed historical start date, not "now").
    """
    stmt = (
        sa.select(Transaction)
        .join(Account, Transaction.account_id == Account.id)
        .where(Account.customer_id == customer_id)
        .order_by(Transaction.ts.desc())
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())


async def post_transaction(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    amount_paise: int,
    direction: TxnDirection | str,
    channel: TxnChannel | str,
    merchant: str | None = None,
    mcc: str | None = None,
    category: str | None = None,
    description: str | None = None,
    ts: datetime | None = None,
    allow_overdraft: bool = False,
) -> Transaction:
    """Post a transaction and atomically update the account balance.

    Locks the account row (``SELECT ... FOR UPDATE``) so simultaneous posts to
    the same account serialise and can't lose an update or race the overdraft
    check. Raises :class:`LedgerError` on overdraft unless ``allow_overdraft``.
    """
    if amount_paise <= 0:
        raise LedgerError("transaction amount must be positive")

    direction = _coerce_direction(direction)
    channel = _coerce_channel(channel)

    # Row lock: concurrent posts to this account block here until we commit.
    locked = await session.execute(
        sa.select(Account).where(Account.id == account_id).with_for_update()
    )
    account = locked.scalar_one_or_none()
    if account is None:
        raise LedgerError(f"account {account_id} not found")

    if direction is TxnDirection.DEBIT:
        new_balance = account.balance_paise - amount_paise
        if new_balance < 0 and not allow_overdraft:
            raise LedgerError(
                f"insufficient funds: balance {account.balance_paise} < debit {amount_paise}"
            )
    else:
        new_balance = account.balance_paise + amount_paise

    account.balance_paise = new_balance

    txn = Transaction(
        account_id=account.id,
        ts=ts or datetime.now(UTC),
        amount_paise=amount_paise,
        direction=direction,
        channel=channel,
        merchant=merchant,
        mcc=mcc,
        category=category,
        balance_after_paise=new_balance,
        description=description,
    )
    session.add(txn)
    await session.flush()
    return txn


async def post_transaction_idempotent(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    event_id: str,
    amount_paise: int,
    direction: TxnDirection | str,
    channel: TxnChannel | str,
    merchant: str | None = None,
    mcc: str | None = None,
    category: str | None = None,
    description: str | None = None,
    ts: datetime | None = None,
    allow_overdraft: bool = True,
) -> Transaction | None:
    """Idempotent variant of :func:`post_transaction`, keyed on ``event_id``.

    Used by the live event-consumer path (``app.workers.event_consumer``), where the
    same Redis Stream entry may be delivered more than once (consumer restarts,
    at-least-once delivery, retries). Returns ``None`` - and leaves the balance
    untouched - if ``event_id`` was already applied; the caller should treat that as
    "already processed" rather than an error.

    ``allow_overdraft`` defaults to ``True`` here (unlike :func:`post_transaction`):
    the sim engine's own overdraft guard already prevented ungenerated debits, so a
    live debit event reaching this far is trusted data, not something to reject.
    """
    if amount_paise <= 0:
        raise LedgerError("transaction amount must be positive")

    direction = _coerce_direction(direction)
    channel = _coerce_channel(channel)

    # Lock the account first so a concurrent duplicate delivery serialises behind
    # this one and reliably observes the row inserted below.
    locked = await session.execute(
        sa.select(Account).where(Account.id == account_id).with_for_update()
    )
    account = locked.scalar_one_or_none()
    if account is None:
        raise LedgerError(f"account {account_id} not found")

    existing = await session.scalar(
        sa.select(Transaction.id).where(Transaction.event_id == event_id)
    )
    if existing is not None:
        return None

    if direction is TxnDirection.DEBIT:
        new_balance = account.balance_paise - amount_paise
        if new_balance < 0 and not allow_overdraft:
            raise LedgerError(
                f"insufficient funds: balance {account.balance_paise} < debit {amount_paise}"
            )
    else:
        new_balance = account.balance_paise + amount_paise
    account.balance_paise = new_balance

    txn = Transaction(
        account_id=account.id,
        event_id=event_id,
        ts=ts or datetime.now(UTC),
        amount_paise=amount_paise,
        direction=direction,
        channel=channel,
        merchant=merchant,
        mcc=mcc,
        category=category,
        balance_after_paise=new_balance,
        description=description,
    )
    session.add(txn)
    try:
        await session.flush()
    except IntegrityError:
        # Lost a race against a concurrent delivery of the same event_id (or a
        # crash-and-retry re-sent it after our own prior attempt actually committed).
        await session.rollback()
        return None
    return txn
