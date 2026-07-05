"""Standing instructions - recurring auto-transfers Sarathi can run for a customer.

A standing instruction debits a chosen account on a fixed cadence (weekly or
monthly) toward a purpose (a savings ``goal``, a fixed deposit ``fd``, or plain
``savings``). Execution is deterministic and honest (see
:mod:`app.services.standing`): every run posts a REAL ledger debit - there are no
fabricated numbers - and, for a goal-linked instruction, adjusts the goal's
balance baseline so moving cash into the goal envelope does not falsely set the
goal back.

The scheduler (:func:`app.services.standing.execute_due_instructions`, wired into
the periodic tick) advances ``next_run_date`` by the cadence and stamps
``last_run_at`` / ``runs_count`` as it runs, so the row is a truthful record of
what actually happened.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin, enum_col
from app.models.enums import StandingCadence, StandingPurpose, StandingStatus

if TYPE_CHECKING:
    from app.models.customer import Customer


class StandingInstruction(UUIDPKMixin, TimestampMixin, Base):
    """A recurring auto-transfer set up by (or for) a customer.

    ``amount_paise`` is always positive (CHECK constraint). ``goal_id`` is set
    only for ``purpose == goal`` instructions; it is ``NULL`` for ``fd`` /
    ``savings``. The instruction is due whenever ``next_run_date <= today`` and
    ``status == active``.
    """

    __tablename__ = "standing_instructions"
    __table_args__ = (
        sa.CheckConstraint("amount_paise > 0", name="ck_standing_instructions_amount_positive"),
        # Serves the due-scan (active + next_run_date) the scheduler runs each tick.
        sa.Index("ix_standing_instructions_status_next_run", "status", "next_run_date"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("customers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    from_account_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[StandingPurpose] = enum_col(StandingPurpose, nullable=False)
    goal_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("savings_goals.id", ondelete="SET NULL"), nullable=True
    )
    amount_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    cadence: Mapped[StandingCadence] = enum_col(StandingCadence, nullable=False)
    next_run_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    status: Mapped[StandingStatus] = enum_col(
        StandingStatus, default=StandingStatus.ACTIVE, index=True, nullable=False
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    runs_count: Mapped[int] = mapped_column(
        sa.Integer, default=0, server_default="0", nullable=False
    )

    customer: Mapped[Customer] = relationship(back_populates="standing_instructions")
