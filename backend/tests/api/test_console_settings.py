"""Console admin controls: runtime settings (`GET/PATCH /console/settings`,
`DELETE /console/settings/{key}`) and the guarded demo reset
(`POST /console/admin/reset-demo`). All staff-gated.

Runs against real Postgres + the flushed test Redis (logical DB 15) - no network
LLM calls anywhere (seeding + settings are pure DB/Redis work).
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import runtime_settings
from app.models.audit import AuditLog
from app.models.customer import Customer
from app.models.identity import User
from tests.api.conftest import auth_cookies

pytestmark = pytest.mark.anyio

SETTINGS_URL = "/api/v1/console/settings"
RESET_URL = "/api/v1/console/admin/reset-demo"


async def _staff(
    make_customer: Callable[..., Any], set_staff_emails: Callable[[str], None]
) -> User:
    user, _customer = await make_customer(email="settings-staff@example.com")
    set_staff_emails("settings-staff@example.com")
    return user


# ===========================================================================
# Runtime settings: read
# ===========================================================================


async def test_get_settings_requires_staff(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer(email="settings-nonstaff@example.com")
    resp = await client.get(SETTINGS_URL, cookies=auth_cookies(user))
    assert resp.status_code == 403


async def test_get_settings_lists_full_allowlist_as_defaults(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    resp = await client.get(SETTINGS_URL, cookies=auth_cookies(staff))
    assert resp.status_code == 200

    settings = resp.json()["settings"]
    keys = [s["key"] for s in settings]
    assert keys == list(runtime_settings.OVERRIDABLE_KEYS)
    # Nothing overridden yet -> every key reports its static default.
    for setting in settings:
        assert setting["source"] == "default"
        assert setting["value"] == setting["default"]

    budget = next(s for s in settings if s["key"] == "llm_daily_budget_usd")
    assert budget["type"] == "float"
    assert budget["min"] == 0.0 and budget["max"] == 10.0

    smart = next(s for s in settings if s["key"] == "openai_model_smart")
    assert smart["type"] == "enum"
    assert smart["options"] == ["gpt-4o-mini", "gpt-4o"]


# ===========================================================================
# Runtime settings: write, validation, audit, read-back, clear
# ===========================================================================


async def test_patch_unknown_key_is_422(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    """Allowlist is enforced at the schema layer (key is a Literal): a key that is
    a real Settings field but NOT overridable is still rejected."""
    staff = await _staff(make_customer, set_staff_emails)
    resp = await client.patch(
        SETTINGS_URL,
        json={"key": "database_url", "value": "postgres://evil"},
        cookies=auth_cookies(staff),
    )
    assert resp.status_code == 422


async def test_patch_bool_override_and_read_back(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)

    resp = await client.patch(
        SETTINGS_URL,
        json={"key": "scheduler_enabled", "value": False},
        cookies=auth_cookies(staff),
    )
    assert resp.status_code == 200
    setting = resp.json()["setting"]
    assert setting["value"] is False
    assert setting["source"] == "override"

    # The effective-value helper the scheduler consumes now returns the override.
    assert await runtime_settings.scheduler_enabled() is False

    # And a fresh GET reflects it as an override.
    got = await client.get(SETTINGS_URL, cookies=auth_cookies(staff))
    entry = next(s for s in got.json()["settings"] if s["key"] == "scheduler_enabled")
    assert entry["value"] is False and entry["source"] == "override"


async def test_patch_budget_clamps_to_range(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    """A budget above the 10.0 ceiling is clamped (a hard spend rail), not stored raw."""
    staff = await _staff(make_customer, set_staff_emails)
    resp = await client.patch(
        SETTINGS_URL,
        json={"key": "llm_daily_budget_usd", "value": 999},
        cookies=auth_cookies(staff),
    )
    assert resp.status_code == 200
    assert resp.json()["setting"]["value"] == 10.0
    assert await runtime_settings.effective_daily_budget_usd() == Decimal("10.0")


async def test_patch_model_enum_rejects_unknown_value(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    bad = await client.patch(
        SETTINGS_URL,
        json={"key": "openai_model_smart", "value": "gpt-5-turbo"},
        cookies=auth_cookies(staff),
    )
    assert bad.status_code == 422

    ok = await client.patch(
        SETTINGS_URL,
        json={"key": "openai_model_smart", "value": "gpt-4o"},
        cookies=auth_cookies(staff),
    )
    assert ok.status_code == 200
    assert ok.json()["setting"]["value"] == "gpt-4o"
    assert await runtime_settings.openai_model_override("smart") == "gpt-4o"


async def test_patch_writes_audit_row_with_old_and_new(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    await client.patch(
        SETTINGS_URL,
        json={"key": "standing_instructions_enabled", "value": False},
        cookies=auth_cookies(staff),
    )

    row = (
        await db.execute(
            select(AuditLog).where(AuditLog.action == "runtime_setting.updated")
        )
    ).scalar_one()
    assert row.actor == staff.email
    assert row.entity == "runtime_setting"
    assert row.entity_id == "standing_instructions_enabled"
    assert row.payload["old"] is None  # was default, no prior override
    assert row.payload["new"] is False


async def test_delete_reverts_to_default(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    await client.patch(
        SETTINGS_URL,
        json={"key": "scheduler_enabled", "value": False},
        cookies=auth_cookies(staff),
    )
    assert await runtime_settings.scheduler_enabled() is False

    resp = await client.delete(
        f"{SETTINGS_URL}/scheduler_enabled", cookies=auth_cookies(staff)
    )
    assert resp.status_code == 200
    assert resp.json()["setting"]["source"] == "default"
    # Reverts to the static config value.
    assert await runtime_settings.get_override("scheduler_enabled") is None

    cleared = (
        await db.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "runtime_setting.cleared")
        )
    ).scalar_one()
    assert cleared == 1


async def test_delete_unknown_key_is_422(
    client: httpx.AsyncClient,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    resp = await client.delete(f"{SETTINGS_URL}/jwt_secret", cookies=auth_cookies(staff))
    assert resp.status_code == 422


# ===========================================================================
# Guarded demo reset
# ===========================================================================


async def test_reset_demo_requires_staff(
    client: httpx.AsyncClient, make_customer: Callable[..., Any]
) -> None:
    user, _customer = await make_customer(email="reset-nonstaff@example.com")
    resp = await client.post(
        RESET_URL, json={"confirm": "RESET"}, cookies=auth_cookies(user)
    )
    assert resp.status_code == 403


async def test_reset_demo_wrong_confirm_is_400_and_touches_nothing(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
) -> None:
    staff = await _staff(make_customer, set_staff_emails)
    before = (await db.execute(select(func.count()).select_from(Customer))).scalar_one()

    resp = await client.post(
        RESET_URL, json={"confirm": "reset"}, cookies=auth_cookies(staff)
    )
    assert resp.status_code == 400

    after = (await db.execute(select(func.count()).select_from(Customer))).scalar_one()
    assert after == before  # nothing reseeded on a failed confirm


async def test_reset_demo_reseeds_and_preserves_identities(
    client: httpx.AsyncClient,
    db: AsyncSession,
    make_customer: Callable[..., Any],
    set_staff_emails: Callable[[str], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact-confirm path reseeds the domain tables while leaving real login
    identities (`users`) untouched, and audit-logs the reset. Uses a tiny cohort
    (monkeypatched) so the real seed path runs fast."""
    import app.api.v1.console as console_module

    monkeypatch.setattr(console_module, "_DEMO_COHORT", 2)
    monkeypatch.setattr(console_module, "_DEMO_MONTHS", 1)

    staff = await _staff(make_customer, set_staff_emails)

    resp = await client.post(
        RESET_URL, json={"confirm": "RESET"}, cookies=auth_cookies(staff)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["reseeded"]["customers"] == 2
    assert "agent_cooldowns" in body["redis_flushed"]

    # Domain tables were reseeded.
    customers = (await db.execute(select(func.count()).select_from(Customer))).scalar_one()
    assert customers == 2

    # The staff user's identity survived the reset (never truncated).
    survived = await db.get(User, staff.id)
    assert survived is not None

    # The reset is on the (freshly restarted) audit chain.
    reset_row = (
        await db.execute(select(AuditLog).where(AuditLog.action == "demo.reset"))
    ).scalar_one()
    assert reset_row.actor == staff.email
    assert reset_row.payload["reseeded"]["customers"] == 2
