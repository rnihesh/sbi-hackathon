"""Auth identity: users, WebAuthn credentials, email OTP codes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin, enum_col
from app.models.enums import CredentialTransport

if TYPE_CHECKING:
    from app.models.customer import Customer


class User(UUIDPKMixin, TimestampMixin, Base):
    """An authenticated identity (Google OAuth / passkey / OTP)."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(sa.String(320), unique=True, index=True, nullable=False)
    google_sub: Mapped[str | None] = mapped_column(
        sa.String(255), unique=True, index=True, nullable=True
    )

    credentials: Mapped[list[Credential]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    customer: Mapped[Customer | None] = relationship(back_populates="user")


class Credential(UUIDPKMixin, TimestampMixin, Base):
    """A registered WebAuthn (passkey) credential for a user."""

    __tablename__ = "credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    credential_id: Mapped[bytes] = mapped_column(sa.LargeBinary, unique=True, nullable=False)
    public_key: Mapped[bytes] = mapped_column(sa.LargeBinary, nullable=False)
    sign_count: Mapped[int] = mapped_column(sa.BigInteger, default=0, nullable=False)
    transport: Mapped[CredentialTransport] = enum_col(
        CredentialTransport, default=CredentialTransport.PLATFORM, nullable=False
    )
    label: Mapped[str | None] = mapped_column(sa.String(120), nullable=True)

    user: Mapped[User] = relationship(back_populates="credentials")


class OtpCode(UUIDPKMixin, TimestampMixin, Base):
    """A one-time email login code (hashed at rest)."""

    __tablename__ = "otp_codes"

    email: Mapped[str] = mapped_column(sa.String(320), index=True, nullable=False)
    code_hash: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    consumed: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
