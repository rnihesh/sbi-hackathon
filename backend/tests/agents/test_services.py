"""Service tests: KYC verifiers, ledger, product matching."""

from __future__ import annotations

import pytest

from app.models.customer import Customer
from app.services import kyc, ledger
from app.services.kyc import KycStatus
from app.services.ledger import LedgerError
from app.services.products import CustomerProfile, match_products

# ---------------------------------------------------------------------------
# KYC
# ---------------------------------------------------------------------------


def test_validate_pan_format() -> None:
    assert kyc.validate_pan("ABCDE1234F")
    assert kyc.validate_pan("abcde1234f")  # normalised to upper
    assert not kyc.validate_pan("ABCD1234F")
    assert not kyc.validate_pan("ABCDE12345")


def test_aadhaar_verhoeff_checksum() -> None:
    base = "23456789012"  # 11 digits, valid leading digit
    full = base + str(kyc.verhoeff_check_digit(base))
    assert kyc.validate_aadhaar(full)
    # Wrong check digit fails.
    wrong = base + str((kyc.verhoeff_check_digit(base) + 1) % 10)
    assert not kyc.validate_aadhaar(wrong)
    # Leading 0/1 rejected, wrong length rejected.
    assert not kyc.validate_aadhaar("123456789012")
    assert not kyc.validate_aadhaar("12345")


def test_name_match_score_is_order_insensitive() -> None:
    assert kyc.name_match_score("Rahul Kumar Sharma", "Sharma Rahul Kumar") > 0.8
    assert kyc.name_match_score("Rahul Sharma", "Zzzz Qqqq") < 0.5


async def test_verify_is_deterministic_and_gates_bad_pan() -> None:
    good = await kyc.verify(name="Rahul Sharma", pan="ABCDE1234F", simulate_latency=False)
    again = await kyc.verify(name="Rahul Sharma", pan="ABCDE1234F", simulate_latency=False)
    assert good.status == again.status  # reproducible, not random
    assert good.pan_valid

    bad = await kyc.verify(name="X", pan="NOTAPAN", simulate_latency=False)
    assert bad.status is KycStatus.FAILED
    assert not bad.pan_valid


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


async def test_open_account_seeds_opening_deposit(db) -> None:  # type: ignore[no-untyped-def]
    customer = Customer(full_name="Ledger User")
    db.add(customer)
    await db.flush()

    account = await ledger.open_account(
        db, customer_id=customer.id, account_type="savings", initial_deposit_paise=100_000
    )
    assert account.balance_paise == 100_000
    assert await ledger.get_balance(db, account.id) == 100_000
    assert await ledger.get_customer_balance(db, customer.id) == 100_000


async def test_post_transaction_updates_balance_and_guards_overdraft(db) -> None:  # type: ignore[no-untyped-def]
    customer = Customer(full_name="Txn User")
    db.add(customer)
    await db.flush()
    account = await ledger.open_account(
        db, customer_id=customer.id, account_type="savings", initial_deposit_paise=100_000
    )

    txn = await ledger.post_transaction(
        db, account_id=account.id, amount_paise=30_000, direction="debit", channel="upi"
    )
    assert txn.balance_after_paise == 70_000
    assert await ledger.get_balance(db, account.id) == 70_000

    with pytest.raises(LedgerError):
        await ledger.post_transaction(
            db, account_id=account.id, amount_paise=1_000_000, direction="debit", channel="upi"
        )


# ---------------------------------------------------------------------------
# Product matching (pure rules)
# ---------------------------------------------------------------------------


def test_match_products_surfaces_insurance_gap_for_dependents() -> None:
    profile = CustomerProfile(
        annual_income_paise=800_000 * 100,
        age=35,
        segment="salaried",
        dependents=2,
        held_product_codes=["savings_account"],
    )
    candidates = match_products(profile)
    codes = [c.code for c in candidates]
    assert "term_insurance" in codes
    term = next(c for c in candidates if c.code == "term_insurance")
    assert any("dependent" in r.lower() for r in term.reasons)


def test_match_products_excludes_held_and_ineligible() -> None:
    profile = CustomerProfile(
        annual_income_paise=150_000 * 100,
        age=17,
        held_product_codes=["savings_account"],
    )
    codes = [c.code for c in match_products(profile, limit=20)]
    assert "savings_account" not in codes  # already held
    assert "credit_card" not in codes  # min age 21
    assert "home_loan" not in codes  # income + age ineligible


def test_match_products_idle_balance_recommends_fd() -> None:
    profile = CustomerProfile(
        annual_income_paise=600_000 * 100,
        age=40,
        held_product_codes=["savings_account", "term_insurance"],
        idle_balance_paise=200_000 * 100,
    )
    candidates = match_products(profile)
    fd = next((c for c in candidates if c.code == "fixed_deposit"), None)
    assert fd is not None
    assert any("idle" in r.lower() for r in fd.reasons)
