"""Direct unit tests for the `get_current_user` / `get_optional_user` dependencies.

These are exercised indirectly by every `/me` test in test_otp.py; this file covers
`get_optional_user` (not yet wired to any Wave 2B route) and the raw 401 path directly.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, get_current_user, get_optional_user
from app.models.identity import User


async def test_get_optional_user_returns_none_without_cookie(db_session: AsyncSession) -> None:
    result = await get_optional_user(sarathi_access=None, db=db_session)
    assert result is None


async def test_get_optional_user_returns_none_for_garbage_token(db_session: AsyncSession) -> None:
    result = await get_optional_user(sarathi_access="not-a-jwt", db=db_session)
    assert result is None


async def test_get_optional_user_returns_user_for_valid_token(db_session: AsyncSession) -> None:
    user = User(email="dep-test@example.com")
    db_session.add(user)
    await db_session.flush()

    token = create_access_token(str(user.id))
    result = await get_optional_user(sarathi_access=token, db=db_session)
    assert result is not None
    assert result.id == user.id


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
