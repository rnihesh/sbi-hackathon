"""Accounts and transactions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin, enum_col
from app.models.enums import AccountStatus, AccountType, TxnChannel, TxnDirection

if TYPE_CHECKING:
    from app.models.customer import Customer


class Account(UUIDPKMixin, TimestampMixin, Base):
    """A customer's bank account."""

    __tablename__ = "accounts"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("customers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    type: Mapped[AccountType] = enum_col(AccountType, nullable=False)
    balance_paise: Mapped[int] = mapped_column(sa.BigInteger, default=0, nullable=False)
    status: Mapped[AccountStatus] = enum_col(
        AccountStatus, default=AccountStatus.ACTIVE, nullable=False
    )
    label: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)

    customer: Mapped[Customer] = relationship(back_populates="accounts")
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class Transaction(UUIDPKMixin, Base):
    """A ledger entry on an account."""

    __tablename__ = "transactions"
    __table_args__ = (sa.Index("ix_transactions_account_ts", "account_id", "ts"),)

    account_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    ts: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    amount_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    direction: Mapped[TxnDirection] = enum_col(TxnDirection, nullable=False)
    channel: Mapped[TxnChannel] = enum_col(TxnChannel, nullable=False)
    merchant: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
    mcc: Mapped[str | None] = mapped_column(sa.String(4), nullable=True)
    category: Mapped[str | None] = mapped_column(sa.String(60), index=True, nullable=True)
    balance_after_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.String(400), nullable=True)

    account: Mapped[Account] = relationship(back_populates="transactions")
