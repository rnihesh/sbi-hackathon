"""Agent outputs surfaced to staff/customers: proposals, nudges, life events."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin, enum_col
from app.models.enums import (
    LifeEventStatus,
    LifeEventType,
    NotificationKind,
    NudgeStatus,
    ProposalKind,
    ProposalStatus,
)

if TYPE_CHECKING:
    from app.models.customer import Customer


class Proposal(UUIDPKMixin, TimestampMixin, Base):
    """An agent-proposed impactful action awaiting human-in-the-loop approval."""

    __tablename__ = "proposals"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("customers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    agent: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    kind: Mapped[ProposalKind] = enum_col(ProposalKind, nullable=False)
    title: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    body: Mapped[str] = mapped_column(sa.Text, nullable=False)
    action: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    status: Mapped[ProposalStatus] = enum_col(
        ProposalStatus, default=ProposalStatus.PENDING, index=True, nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)

    customer: Mapped[Customer] = relationship(back_populates="proposals")
    nudges: Mapped[list[Nudge]] = relationship(back_populates="proposal")


class Nudge(UUIDPKMixin, TimestampMixin, Base):
    """A contextual nudge delivered to a customer."""

    __tablename__ = "nudges"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("customers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("proposals.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    body: Mapped[str] = mapped_column(sa.Text, nullable=False)
    cta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    status: Mapped[NudgeStatus] = enum_col(NudgeStatus, default=NudgeStatus.SENT, nullable=False)

    customer: Mapped[Customer] = relationship(back_populates="nudges")
    proposal: Mapped[Proposal | None] = relationship(back_populates="nudges")


class Notification(UUIDPKMixin, TimestampMixin, Base):
    """A customer-facing notification: something real happened for this customer.

    Created from genuine moments (an offer executed, a life event detected, an
    account opened, a nudge delivered, demo activity readied), never synthesised.
    ``link`` is an app-relative path (e.g. ``/app/nudges``) the client navigates
    to on click.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        # Serves the inbox query (newest-first for a customer) and the unread
        # count without a separate index.
        sa.Index("ix_notifications_customer_created", "customer_id", "created_at"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("customers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[NotificationKind] = enum_col(NotificationKind, nullable=False)
    title: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    body: Mapped[str] = mapped_column(sa.Text, nullable=False)
    link: Mapped[str | None] = mapped_column(sa.String(300), nullable=True)
    read: Mapped[bool] = mapped_column(
        sa.Boolean, default=False, server_default=sa.false(), nullable=False
    )

    customer: Mapped[Customer] = relationship(back_populates="notifications")


class LifeEvent(UUIDPKMixin, Base):
    """A detected life event driving next-best-action outreach."""

    __tablename__ = "life_events"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("customers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    type: Mapped[LifeEventType] = enum_col(LifeEventType, nullable=False)
    confidence: Mapped[float] = mapped_column(sa.Float, default=0.0, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    detected_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    status: Mapped[LifeEventStatus] = enum_col(
        LifeEventStatus, default=LifeEventStatus.DETECTED, nullable=False
    )

    customer: Mapped[Customer] = relationship(back_populates="life_events")
