"""Agent memory: episodic recall, facts, and preferences (pgvector-backed)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin, enum_col
from app.models.enums import MemoryKind

if TYPE_CHECKING:
    from app.models.customer import Customer

EMBEDDING_DIM = 1536
"""Dimensionality of stored embeddings (OpenAI text-embedding-3-small)."""


class AgentMemory(UUIDPKMixin, TimestampMixin, Base):
    """A single memory item for a customer, retrievable by vector similarity."""

    __tablename__ = "agent_memories"
    __table_args__ = (sa.Index("ix_agent_memories_customer_kind", "customer_id", "kind"),)

    customer_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[MemoryKind] = enum_col(MemoryKind, nullable=False)
    text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)

    customer: Mapped[Customer] = relationship(back_populates="memories")
