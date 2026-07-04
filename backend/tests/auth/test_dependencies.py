"""Direct unit tests for the `get_current_user` / `get_optional_user` dependencies.

These are exercised indirectly by every `/me` test in test_otp.py; this file covers
`get_optional_user`'s three-state contract (absent cookie -> None; present-but-broken
cookie -> 401; valid cookie -> User) and the raw `get_current_user` 401 path directly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import (
    TokenType,
    create_access_token,
    get_current_user,
    get_optional_user,
)
from app.models.identity import User


def _expired_access_token(subject: str) -> str:
    """Mint a well-formed but already-expired access token for ``subject``."""
    settings = get_settings()
    now = datetime.now(tz=UTC)
    payload = {
        "sub": subject,
        "type": TokenType.ACCESS.value,
        "iat": int((now - timedelta(minutes=30)).timestamp()),
        "exp": int((now - timedelta(minutes=15)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


# --- get_optional_user: three-state contract -----------------------------------------


async def test_get_optional_user_returns_none_without_cookie(db_session: AsyncSession) -> None:
    """State 1: no cookie at all -> anonymous (None), so anon chat keeps working."""
    result = await get_optional_user(sarathi_access=None, db=db_session)
    assert result is None


async def test_get_optional_user_returns_user_for_valid_token(db_session: AsyncSession) -> None:
    """State 2: a valid cookie -> the resolved user."""
    user = User(email="dep-test@example.com")
    db_session.add(user)
    await db_session.flush()

    token = create_access_token(str(user.id))
    result = await get_optional_user(sarathi_access=token, db=db_session)
    assert result is not None
    assert result.id == user.id


async def test_get_optional_user_raises_401_for_garbage_token(db_session: AsyncSession) -> None:
    """State 3a: a present but malformed cookie is a broken session, not anonymous."""
    with pytest.raises(HTTPException) as exc_info:
        await get_optional_user(sarathi_access="not-a-jwt", db=db_session)
    assert exc_info.value.status_code == 401


async def test_get_optional_user_raises_401_for_expired_token(db_session: AsyncSession) -> None:
    """State 3b: a present but expired cookie must 401 so the frontend refreshes."""
    user = User(email="dep-expired@example.com")
    db_session.add(user)
    await db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        await get_optional_user(sarathi_access=_expired_access_token(str(user.id)), db=db_session)
    assert exc_info.value.status_code == 401


async def test_get_optional_user_raises_401_for_unknown_user_id(db_session: AsyncSession) -> None:
    """State 3c: a well-signed token naming a deleted/unknown user is still broken."""
    token = create_access_token(str(uuid.uuid4()))
    with pytest.raises(HTTPException) as exc_info:
        await get_optional_user(sarathi_access=token, db=db_session)
    assert exc_info.value.status_code == 401


async def test_get_current_user_raises_401_without_cookie(db_session: AsyncSession) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(sarathi_access=None, db=db_session)
    assert exc_info.value.status_code == 401


async def test_get_current_user_raises_401_for_unknown_user_id(db_session: AsyncSession) -> None:
    token = create_access_token(str(uuid.uuid4()))
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(sarathi_access=token, db=db_session)
    assert exc_info.value.status_code == 401


async def test_get_current_user_returns_user_for_valid_token(db_session: AsyncSession) -> None:
    user = User(email="dep-test-2@example.com")
    db_session.add(user)
    await db_session.flush()

    token = create_access_token(str(user.id))
    result = await get_current_user(sarathi_access=token, db=db_session)
    assert result.id == user.id
