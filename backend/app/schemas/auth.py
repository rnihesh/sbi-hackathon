"""Pydantic v2 request/response schemas for the auth API surface.

These are the exact wire shapes the Wave 3 frontend integrates against.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class MessageResponse(BaseModel):
    """Generic ack payload for endpoints that don't return a resource."""

    message: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    created_at: datetime


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    email: str | None
    phone: str | None
    city: str | None
    state: str | None
    segment: str | None
    digital_maturity: str
    preferred_language: str | None


class MeResponse(BaseModel):
    user: UserOut
    customer: CustomerOut | None = None
    is_staff: bool = False


# --- OTP ---------------------------------------------------------------------------


class OtpSendRequest(BaseModel):
    email: EmailStr


class OtpVerifyRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


# --- Passkeys ------------------------------------------------------------------------


class PasskeyRegisterCompleteRequest(BaseModel):
    """Body for ``POST /auth/passkey/register/complete``.

    ``credential`` is exactly the ``RegistrationResponseJSON`` object returned by the
    browser's ``navigator.credentials.create()`` (e.g. via `@simplewebauthn/browser`'s
    `startRegistration()`).
    """

    credential: dict[str, Any]
    label: str | None = None


class PasskeyRegisterCompleteResponse(BaseModel):
    credential_id: str
    label: str
    transport: str


class PasskeyCredentialOut(BaseModel):
    id: str
    label: str
    transport: str
    created_at: datetime


class PasskeyCredentialListResponse(BaseModel):
    credentials: list[PasskeyCredentialOut]


class SessionOut(BaseModel):
    """One active session, as reported by ``GET /auth/sessions``.

    ``jti_suffix`` is the last few characters of the session's Redis-tracked refresh
    jti - enough to disambiguate in the UI and identify it for revocation, never the
    full jti. ``created_at``/``last_seen_at`` are unset for a session that predates
    the metadata upgrade (see ``app.core.security``); the frontend should treat that
    the same as an unrecognised device, not an error.
    """

    jti_suffix: str
    device: str
    created_at: datetime | None
    last_seen_at: datetime | None
    current: bool


class PasskeyLoginBeginRequest(BaseModel):
    email: EmailStr | None = None


class PasskeyLoginCompleteRequest(BaseModel):
    """Body for ``POST /auth/passkey/login/complete``.

    ``credential`` is exactly the ``AuthenticationResponseJSON`` object returned by
    ``navigator.credentials.get()`` (e.g. via `@simplewebauthn/browser`'s
    `startAuthentication()`).
    """

    credential: dict[str, Any]
