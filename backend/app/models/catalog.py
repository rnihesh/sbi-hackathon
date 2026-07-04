"""Product catalog and per-customer holdings."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin, enum_col
from app.models.enums import HoldingStatus

if TYPE_CHECKING:
    from app.models.customer import Customer


class Product(UUIDPKMixin, TimestampMixin, Base):
    """A bank product in the catalog."""

    __tablename__ = "products"

    code: Mapped[str] = mapped_column(sa.String(60), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    category: Mapped[str] = mapped_column(sa.String(60), index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    eligibility: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )

    holdings: Mapped[list[Holding]] = relationship(back_populates="product")


class Holding(UUIDPKMixin, TimestampMixin, Base):
    """A customer's relationship to a product (offered / active / dormant)."""

    __tablename__ = "holdings"
    __table_args__ = (
        sa.UniqueConstraint("customer_id", "product_id", name="uq_holding_customer_product"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("customers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("products.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[HoldingStatus] = enum_col(
        HoldingStatus, default=HoldingStatus.OFFERED, nullable=False
    )

    customer: Mapped[Customer] = relationship(back_populates="holdings")
    product: Mapped[Product] = relationship(back_populates="holdings")
