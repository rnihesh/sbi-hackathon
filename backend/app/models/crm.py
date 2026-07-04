"""Sales leads / prospects for the acquisition funnel."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin, enum_col
from app.models.enums import LeadStage

if TYPE_CHECKING:
    from app.models.customer import Customer


class Lead(UUIDPKMixin, TimestampMixin, Base):
    """An acquisition lead. May link to a :class:`Customer` once converted.

    Prospect contact fields (name/email/phone) are included so a lead is useful
    before a customer record exists.
    """

    __tablename__ = "leads"

    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("customers.id", ondelete="SET NULL"), index=True, nullable=True
    )
    source: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    name: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
    email: Mapped[str | None] = mapped_column(sa.String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(sa.String(20), nullable=True)
    intent_score: Mapped[float] = mapped_column(sa.Float, default=0.0, nullable=False)
    stage: Mapped[LeadStage] = enum_col(LeadStage, default=LeadStage.NEW, nullable=False)
    notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    customer: Mapped[Customer | None] = relationship(back_populates="leads")
