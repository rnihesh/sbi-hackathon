"""Unit tests for the demo-activity helpers (pure functions + LLM flavour pass).

No DB or network: the persona flavour pass is driven by a scripted FakeRouter,
and the merchant-threading / pollution-cleanup helpers are pure functions.
"""

from __future__ import annotations

from datetime import datetime

import orjson

from app.api.v1.demo import (
    _apply_flavor,
    _clear_demo_pollution,
    _persona_flavor,
)
from app.models.customer import Customer
from app.models.enums import DigitalMaturity
from app.sim import personas
from app.sim.generator import Channel, Direction, Txn
from tests.agents.conftest import FakeRouter, make_response


def _txn(category: str, direction: Direction = Direction.DEBIT, merchant: str = "DMart") -> Txn:
    return Txn(
        event_id="e1",
        customer_id="c1",
        ts=datetime(2024, 6, 1, 12, 0),
        amount_paise=25_000,
        direction=direction,
        channel=Channel.UPI,
        merchant=merchant,
        mcc=None,
        category=category,
        balance_after_paise=100_000,
        description="x",
    )


def test_apply_flavor_reskins_only_retail_debits() -> None:
    txns = [
        _txn("groceries", merchant="DMart"),
        _txn("food_delivery", merchant="Swiggy"),
        _txn("salary", direction=Direction.CREDIT, merchant="Employer"),
        _txn("rent", merchant="Landlord Properties"),
    ]
    merchants = ["Local Kirana Mart", "Corner Cafe"]

    out = _apply_flavor(txns, merchants, salt=12345)

    # Income and rent keep structural merchant labels.
    assert out[2].merchant == "Employer"
    assert out[3].merchant == "Landlord Properties"
    # Retail debits are only ever replaced with a provided flavour name.
    for original, updated in zip(txns[:2], out[:2], strict=True):
        assert updated.merchant in {original.merchant, *merchants}


def test_apply_flavor_is_deterministic_for_a_salt() -> None:
    txns = [_txn("groceries") for _ in range(20)]
    merchants = ["A", "B", "C"]

    first = [t.merchant for t in _apply_flavor(txns, merchants, salt=99)]
    second = [t.merchant for t in _apply_flavor(txns, merchants, salt=99)]

    assert first == second
    # At least one of twenty retail debits gets reskinned (guards the threading).
    assert any(m in merchants for m in first)


def test_apply_flavor_noop_without_merchants() -> None:
    txns = [_txn("groceries", merchant="DMart")]
    assert _apply_flavor(txns, [], salt=1) == txns


def test_clear_demo_pollution_nulls_matching_identity_fields() -> None:
    customer = Customer(
        full_name="Asha",
        city="Pune",
        occupation="Software Engineer",
        segment="salaried",
        annual_income_paise=1_200_000 * 100,
        persona={
            "archetype": personas.Archetype.YOUNG_SALARIED_TECHIE.value,
            "city": "Pune",
            "occupation": "Software Engineer",
            "monthly_income_paise": 100_000 * 100,
        },
    )

    changed = _clear_demo_pollution(customer)

    assert changed is True
    assert customer.city is None
    assert customer.occupation is None
    assert customer.segment is None
    assert customer.annual_income_paise is None


def test_clear_demo_pollution_ignores_non_demo_customer() -> None:
    customer = Customer(full_name="Real User", city="Delhi", persona={})
    assert _clear_demo_pollution(customer) is False
    assert customer.city == "Delhi"  # untouched


def test_clear_demo_pollution_keeps_mismatched_values() -> None:
    # A demo persona is attached but the columns were hand-edited: leave them.
    customer = Customer(
        full_name="Edited",
        city="Mumbai",  # persona says Pune -> not our pollution
        persona={
            "archetype": personas.Archetype.YOUNG_SALARIED_TECHIE.value,
            "city": "Pune",
        },
    )
    assert _clear_demo_pollution(customer) is False
    assert customer.city == "Mumbai"


async def test_persona_flavor_parses_valid_json() -> None:
    persona = personas.make_cohort(1, seed=7)[0]
    flavor_json = {
        "employer_name": "Coastal Traders",
        "merchant_flavor": ["Kirana One", "  ", "Cafe Two", "Metro Three"],
        "spending_note": "Frugal saver.",
    }
    router = FakeRouter(lambda **_: make_response(orjson.dumps(flavor_json).decode()))

    result = await _persona_flavor(router, persona, "cid")

    assert result is not None
    assert result["employer_name"] == "Coastal Traders"
    # Blank merchant entries are dropped.
    assert result["merchant_flavor"] == ["Kirana One", "Cafe Two", "Metro Three"]
    call = router.calls[0]
    assert call["tier"] == "fast"
    assert call["json_mode"] is True
    assert call["purpose"] == "demo:persona_flavor"


async def test_persona_flavor_returns_none_on_bad_json() -> None:
    persona = personas.make_cohort(1, seed=7)[0]
    router = FakeRouter(lambda **_: make_response("not json at all"))

    assert await _persona_flavor(router, persona, "cid") is None


def test_maturity_enum_thresholds_are_sane() -> None:
    from app.api.v1.demo import _maturity_enum

    assert _maturity_enum(0.9) is DigitalMaturity.HIGH
    assert _maturity_enum(0.5) is DigitalMaturity.MEDIUM
    assert _maturity_enum(0.1) is DigitalMaturity.LOW
