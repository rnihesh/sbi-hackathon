"""Chat conversations and messages."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin, enum_col
from app.models.enums import ConversationChannel, MessageRole

if TYPE_CHECKING:
    from app.models.customer import Customer


class Conversation(UUIDPKMixin, TimestampMixin, Base):
    """A chat session between a customer and the agent mesh."""

    __tablename__ = "conversations"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("customers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    channel: Mapped[ConversationChannel] = enum_col(
        ConversationChannel, default=ConversationChannel.APP, nullable=False
    )
    title: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)

    customer: Mapped[Customer] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(UUIDPKMixin, TimestampMixin, Base):
    """A single turn in a conversation."""

    __tablename__ = "messages"
    __table_args__ = (
        sa.Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[MessageRole] = enum_col(MessageRole, nullable=False)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
