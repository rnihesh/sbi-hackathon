"""Shared ORM base, mixins, and column helpers."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, MappedColumn, mapped_column

from app.core.db import Base

__all__ = ["Base", "TimestampMixin", "UUIDPKMixin", "enum_col", "utcnow"]


def utcnow() -> sa.sql.functions.Function[Any]:
    """Server-side ``now()`` for timestamp defaults."""
    return sa.func.now()


class UUIDPKMixin:
    """Adds a UUID primary key with a Python-side ``uuid4`` default."""

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )


class TimestampMixin:
    """Adds a server-defaulted ``created_at`` column."""

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def enum_col(enum_cls: type[enum.Enum], **kwargs: Any) -> MappedColumn[Any]:
    """Return a mapped column persisting ``enum_cls`` as VARCHAR + CHECK constraint.

    Uses ``values_callable`` so the enum's *values* (not member names) are stored.
    """
    return mapped_column(
        sa.Enum(
            enum_cls,
            native_enum=False,
            length=32,
            values_callable=lambda e: [str(m.value) for m in e],
        ),
        **kwargs,
    )
