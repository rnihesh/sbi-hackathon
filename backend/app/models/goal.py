"""Customer savings goals - a coaching target Sarathi's agents can track toward.

Progress is deterministic and honest (see :mod:`app.services.goals`): a goal
captures the customer's total balance across accounts at creation time as
``baseline_paise``, and progress is how much the balance has grown since. There
is no per-goal earmarking of funds, so concurrent goals share the same balance
growth - the UI says so plainly.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin, enum_col
from app.models.enums import GoalStatus

if TYPE_CHECKING:
    from app.models.customer import Customer


class SavingsGoal(UUIDPKMixin, TimestampMixin, Base):
    """A savings target set by (or for) a customer.

    ``target_paise`` is always positive (enforced by a CHECK constraint). A goal
    flips from ``active`` to ``achieved`` (stamping ``achieved_at``) the moment
    computed progress reaches the target; it stays visible until the customer
    ``archived`` it. Archiving is a soft hide (the row survives); DELETE removes
    it outright.
    """

    __tablename__ = "savings_goals"
    __table_args__ = (
        sa.CheckConstraint("target_paise > 0", name="ck_savings_goals_target_positive"),
        # Serves the "this customer's goals, newest-first" list query.
        sa.Index("ix_savings_goals_customer_created", "customer_id", "created_at"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("customers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    target_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    # The customer's total balance at goal-creation time; progress is measured
    # relative to this. Zero for a customer with no accounts yet.
    baseline_paise: Mapped[int] = mapped_column(
        sa.BigInteger, default=0, server_default="0", nullable=False
    )
    target_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    status: Mapped[GoalStatus] = enum_col(
        GoalStatus, default=GoalStatus.ACTIVE, nullable=False
    )
    achieved_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    customer: Mapped[Customer] = relationship(back_populates="savings_goals")
