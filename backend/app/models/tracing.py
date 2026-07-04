"""Glass-box tracing: agent runs, steps, and raw LLM calls."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin, enum_col
from app.models.enums import AgentRunStatus, AgentStepKind, AgentTriggerType, LlmTier

if TYPE_CHECKING:
    from app.models.customer import Customer

_COST = sa.Numeric(14, 6)


class AgentRun(UUIDPKMixin, Base):
    """One execution of an agent graph (chat turn or event handling)."""

    __tablename__ = "agent_runs"

    agent: Mapped[str] = mapped_column(sa.String(80), index=True, nullable=False)
    trigger: Mapped[AgentTriggerType] = enum_col(AgentTriggerType, nullable=False)
    status: Mapped[AgentRunStatus] = enum_col(
        AgentRunStatus, default=AgentRunStatus.RUNNING, nullable=False
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("customers.id", ondelete="SET NULL"), index=True, nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    tokens_in: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(_COST, default=Decimal("0"), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    customer: Mapped[Customer | None] = relationship(back_populates="agent_runs")
    steps: Mapped[list[AgentStep]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentStep.seq",
    )


class AgentStep(UUIDPKMixin, Base):
    """A single node execution inside an :class:`AgentRun`."""

    __tablename__ = "agent_steps"
    __table_args__ = (sa.Index("ix_agent_steps_run_seq", "run_id", "seq"),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    node: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    kind: Mapped[AgentStepKind] = enum_col(AgentStepKind, nullable=False)
    name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    input: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    model: Mapped[str | None] = mapped_column(sa.String(80), nullable=True)
    tokens_in: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(_COST, default=Decimal("0"), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )

    run: Mapped[AgentRun] = relationship(back_populates="steps")


class LlmCall(UUIDPKMixin, TimestampMixin, Base):
    """A single provider call recorded by the LLM router (cost ledger)."""

    __tablename__ = "llm_calls"

    provider: Mapped[str] = mapped_column(sa.String(40), index=True, nullable=False)
    model: Mapped[str] = mapped_column(sa.String(80), index=True, nullable=False)
    tier: Mapped[LlmTier] = enum_col(LlmTier, nullable=False)
    tokens_in: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(_COST, default=Decimal("0"), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    ok: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    purpose: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)
