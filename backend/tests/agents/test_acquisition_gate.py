"""Acquisition KYC gate: open_account must refuse until KYC is verified."""

from __future__ import annotations

from app.agents import acquisition
from app.agents.state import new_state
from tests.agents.conftest import FakeRouter, ScriptedHandler


async def test_open_account_refuses_when_kyc_unverified(make_ctx) -> None:  # type: ignore[no-untyped-def]
    ctx = await make_ctx(FakeRouter(ScriptedHandler()))
    state = new_state(conversation_id="c", customer_id=None, user_text="open a savings account")

    # KYC bag exists with name+PAN but status is NOT verified.
    bag = acquisition._kyc_bag(state)
    bag.update({"name": "Rahul Sharma", "pan": "ABCDE1234F"})

    result = await acquisition._open_account(ctx, state, {"account_type": "savings"})
    assert result["opened"] is False
    assert "not verified" in result["error"].lower()
    assert ctx.customer_id is None  # no customer created


async def test_open_account_succeeds_after_verified(make_ctx) -> None:  # type: ignore[no-untyped-def]
    ctx = await make_ctx(FakeRouter(ScriptedHandler()))
    state = new_state(conversation_id="c", customer_id=None, user_text="open a savings account")

    bag = acquisition._kyc_bag(state)
    bag.update({"name": "Rahul Sharma", "pan": "ABCDE1234F", "status": "verified"})

    result = await acquisition._open_account(
        ctx, state, {"account_type": "savings", "initial_deposit_rupees": 1000}
    )
    assert result["opened"] is True
    assert result["balance_paise"] == 100_000  # ₹1000 → paise
    assert ctx.customer_id is not None
    assert state["customer_id"] == result["customer_id"]


async def test_collect_kyc_field_validates_pan(make_ctx) -> None:  # type: ignore[no-untyped-def]
    ctx = await make_ctx(FakeRouter(ScriptedHandler()))
    state = new_state(conversation_id="c", customer_id=None, user_text="onboarding")

    bad = await acquisition._collect_kyc_field(ctx, state, {"field": "pan", "value": "NOPE"})
    assert bad["valid"] is False

    good = await acquisition._collect_kyc_field(ctx, state, {"field": "pan", "value": "ABCDE1234F"})
    assert good["valid"] is True
    assert acquisition._kyc_bag(state)["pan"] == "ABCDE1234F"
