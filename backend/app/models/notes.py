"""Staff-authored notes on a customer's 360 profile.

A small internal RM tool, deliberately separate from the agent-generated
activity timeline (`GET /console/customers/{id}/timeline`): a note is a staff
observation, not something that happened, so it gets its own card rather than
polluting the merged feed.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.customer import Customer


class StaffNote(UUIDPKMixin, TimestampMixin, Base):
    """One staff note on a customer. Any staff member may delete any note (small
    team tool - no per-author ownership check on delete)."""

    __tablename__ = "staff_notes"
    __table_args__ = (
        # Serves the "newest-first notes for this customer" list query without a
        # separate index (mirrors `ix_notifications_customer_created`).
        sa.Index("ix_staff_notes_customer_created", "customer_id", "created_at"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("customers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    author_email: Mapped[str] = mapped_column(sa.String(320), nullable=False)
    text: Mapped[str] = mapped_column(sa.String(1000), nullable=False)

    customer: Mapped[Customer] = relationship(back_populates="staff_notes")
