"""Immutable, hash-chained audit log."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

import orjson
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPKMixin

GENESIS_HASH = "0" * 64
"""``prev_hash`` value used for the first row in the chain."""


def chain_hash(prev_hash: str, record: dict[str, Any]) -> str:
    """Compute ``sha256(prev_hash + canonical(record))`` as a hex digest.

    ``record`` is serialised canonically (sorted keys) so the digest is stable and
    independently verifiable.
    """
    canonical = orjson.dumps(record, option=orjson.OPT_SORT_KEYS)
    digest = hashlib.sha256(prev_hash.encode("utf-8") + canonical)
    return digest.hexdigest()


class AuditLog(UUIDPKMixin, Base):
    """A tamper-evident audit record. Each row's ``hash`` chains from ``prev_hash``."""

    __tablename__ = "audit_logs"

    ts: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), index=True, nullable=False
    )
    actor: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    action: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    entity: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(sa.String(80), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    prev_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    hash: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
