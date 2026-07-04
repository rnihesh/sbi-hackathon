"""Customer profile (prospects may exist before a linked user)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin, enum_col
from app.models.enums import DigitalMaturity

if TYPE_CHECKING:
    from app.models.banking import Account
    from app.models.catalog import Holding
    from app.models.conversation import Conversation
    from app.models.crm import Lead
    from app.models.engagement import LifeEvent, Nudge, Proposal
    from app.models.identity import User
    from app.models.memory import AgentMemory
    from app.models.tracing import AgentRun


class Customer(UUIDPKMixin, TimestampMixin, Base):
    """A banking customer or prospect.

    ``user_id`` is optional: prospects are created by the acquisition flow before an
    authenticated user exists, then linked on sign-up.
    """

    __tablename__ = "customers"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), unique=True, nullable=True
    )

    # --- profile ---
    full_name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(sa.String(320), index=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(sa.String(20), index=True, nullable=True)
    city: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    state: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    occupation: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
    annual_income_paise: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    segment: Mapped[str | None] = mapped_column(sa.String(60), nullable=True)

    # --- persona / risk ---
    persona: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    digital_maturity: Mapped[DigitalMaturity] = enum_col(
        DigitalMaturity, default=DigitalMaturity.MEDIUM, nullable=False
    )
    churn_risk: Mapped[float] = mapped_column(sa.Float, default=0.0, nullable=False)

    # --- relationships ---
    user: Mapped[User | None] = relationship(back_populates="customer")
    accounts: Mapped[list[Account]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    holdings: Mapped[list[Holding]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    proposals: Mapped[list[Proposal]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    nudges: Mapped[list[Nudge]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    life_events: Mapped[list[LifeEvent]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    memories: Mapped[list[AgentMemory]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    agent_runs: Mapped[list[AgentRun]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    leads: Mapped[list[Lead]] = relationship(back_populates="customer")
