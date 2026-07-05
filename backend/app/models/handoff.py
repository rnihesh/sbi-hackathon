"""Human-handoff requests: the moment the agent steps aside for a person.

A ``HandoffRequest`` is created when Sarathi decides (or is deterministically
nudged) to escalate a conversation to a human relationship manager - the user
asked for a person, is stuck after repeated failures, raised a complaint or
fraud concern, or wants something outside agent authority. It is deliberately
its own table (not a ``Proposal``): a proposal is an agent action awaiting
approval, whereas a handoff is the agent *declining to act* and queuing a person.

``customer_id`` is nullable because anonymous prospects can ask for a human too;
``conversation_id`` is always stored so an anonymous handoff still points staff
at the exact thread.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin, enum_col
from app.models.enums import HandoffStatus, HandoffUrgency

if TYPE_CHECKING:
    from app.models.customer import Customer


class HandoffRequest(UUIDPKMixin, TimestampMixin, Base):
    """One request to route a conversation to a human relationship manager."""

    __tablename__ = "handoff_requests"
    __table_args__ = (
        # Serves the dedup guard ("is there already an active handoff for this
        # conversation?") and the queue's open-first ordering by status.
        sa.Index("ix_handoff_requests_conversation", "conversation_id"),
    )

    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("customers.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # Always present, even for anonymous prospects (may be a non-UUID thread id).
    conversation_id: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    reason: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    urgency: Mapped[HandoffUrgency] = enum_col(
        HandoffUrgency, default=HandoffUrgency.NORMAL, nullable=False
    )
    status: Mapped[HandoffStatus] = enum_col(
        HandoffStatus, default=HandoffStatus.OPEN, index=True, nullable=False
    )
    claimed_by: Mapped[str | None] = mapped_column(sa.String(320), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(sa.String(1000), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    # One-directional (nullable FK): staff read the customer name via selectinload;
    # no back_populates on Customer keeps this table self-contained.
    customer: Mapped[Customer | None] = relationship("Customer", lazy="selectin")
