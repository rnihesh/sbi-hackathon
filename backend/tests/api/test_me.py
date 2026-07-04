"""`GET /me`'s `is_staff` flag: must agree with `get_current_staff`'s own rule."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from tests.api.conftest import auth_cookies


async def test_me_is_staff_true_when_email_allowlisted(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    user, _customer = await make_customer(email="staff-me@example.com")
    set_staff_emails("staff-me@example.com")

    resp = await client.get("/api/v1/me", cookies=auth_cookies(user))
    assert resp.status_code == 200
    assert resp.json()["is_staff"] is True


async def test_me_is_staff_false_when_not_allowlisted(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    user, _customer = await make_customer(email="not-staff-me@example.com")
    set_staff_emails("someone-else@example.com")

    resp = await client.get("/api/v1/me", cookies=auth_cookies(user))
    assert resp.status_code == 200
    assert resp.json()["is_staff"] is False


async def test_me_is_staff_agrees_with_console_gate(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    """`is_staff` and the real `/console/*` 403 gate must never disagree."""
    user, _customer = await make_customer(email="agree-check@example.com")
    set_staff_emails("agree-check@example.com")

    me_resp = await client.get("/api/v1/me", cookies=auth_cookies(user))
    leads_resp = await client.get("/api/v1/console/leads", cookies=auth_cookies(user))

    assert me_resp.json()["is_staff"] is True
    assert leads_resp.status_code == 200
