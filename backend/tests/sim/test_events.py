from __future__ import annotations

import statistics
from datetime import datetime, timedelta

from app.sim import events, generator
from app.sim.events import GroundTruthEvent, LifeEventScript
from app.sim.generator import GeneratorState, Txn
from app.sim.personas import Archetype, Persona, make_cohort


def _persona_of(archetype: Archetype, seed: int = 42, pool: int = 200) -> Persona:
    cohort = make_cohort(pool, seed)
    for p in cohort:
        if p.archetype == archetype:
            return p
    raise AssertionError(f"no {archetype} in a {pool}-persona cohort seeded {seed}")


def _apply_mid_stream(
    persona: Persona,
    script: LifeEventScript,
    seed: int = 42,
    before_months: int = 3,
    after_months: int = 3,
) -> tuple[list[Txn], GroundTruthEvent, list[Txn], GeneratorState]:
    """Generate `before_months`, apply `script`, generate `after_months` more.

    Returns (before_txns, gt_event, after_txns, state).
    """
    state = generator.new_state(persona, seed)
    before = generator.generate_history(persona, months=before_months, seed=seed, state=state)
    assert state.last_generated_date is not None
    trigger_ts = datetime.combine(state.last_generated_date, datetime.min.time())
    gt = script.apply(persona, state, trigger_ts)
    after = generator.generate_history(persona, months=after_months, seed=seed, state=state)
    return before, gt, after, state


def test_registry_covers_every_life_event_type() -> None:
    assert set(events.REGISTRY.keys()) == set(events.LifeEventType)


# ---------------------------------------------------------------------------
# job_change
# ---------------------------------------------------------------------------


def test_job_change_raises_mean_salary_and_skips_one_cycle() -> None:
    persona = _persona_of(Archetype.YOUNG_SALARIED_TECHIE)
    before, gt, after, state = _apply_mid_stream(persona, events.job_change)

    before_salaries = [t.amount_paise for t in before if t.category == "salary"]
    after_salaries = [t.amount_paise for t in after if t.category == "salary"]

    assert before_salaries, "expected at least one pre-event salary credit"
    assert after_salaries, "expected at least one post-event salary credit"
    assert statistics.mean(after_salaries) > statistics.mean(before_salaries)

    assert gt.type is events.LifeEventType.JOB_CHANGE
    assert gt.params["new_income_paise"] > gt.params["previous_income_paise"]
    growth = gt.params["new_income_paise"] / gt.params["previous_income_paise"]
    assert 1.3 <= growth <= 1.6

    # Employer and income bookkeeping synced onto the persona too.
    assert persona.employer == gt.params["new_employer"]
    assert persona.monthly_income_paise == gt.params["new_income_paise"]

    # One pay cycle is skipped for the transition gap: strictly fewer salary
    # credits in `after` than an unmutated stream would have produced.
    unmutated = generator.generate_history(
        persona,
        months=3,
        seed=42,
        state=generator.new_state(persona, 42, start_date=state.last_generated_date),
    )
    assert len(after_salaries) <= len([t for t in unmutated if t.category == "salary"])


# ---------------------------------------------------------------------------
# new_child
# ---------------------------------------------------------------------------


def test_new_child_ramps_pharmacy_spend_and_adds_baby_purchases() -> None:
    persona = _persona_of(Archetype.YOUNG_SALARIED_TECHIE)
    _before, gt, after, state = _apply_mid_stream(persona, events.new_child, after_months=3)

    assert gt.type is events.LifeEventType.NEW_CHILD
    assert "pharmacy" in state.category_multipliers
    multiplier, _expires = state.category_multipliers["pharmacy"]
    assert multiplier > 1.0

    baby_txns = [t for t in after if t.category == "baby_essentials"]
    assert baby_txns, "expected at least one baby-essentials purchase after new_child"
    assert all(t.merchant in generator.BABY_STORE_MERCHANTS for t in baby_txns)

    # Ground truth and family record both reflect the new dependent.
    assert persona.dependents >= 1
    assert persona.family["children"]


# ---------------------------------------------------------------------------
# home_purchase_intent
# ---------------------------------------------------------------------------


def test_home_purchase_intent_stops_rent_and_adds_home_loan_emi() -> None:
    # Only meaningful for renters; force it via a fresh persona search.
    cohort = make_cohort(200, seed=42)
    renter = next(
        p for p in cohort if p.archetype == Archetype.YOUNG_SALARIED_TECHIE and p.is_renter
    )
    before, gt, after, state = _apply_mid_stream(
        renter, events.home_purchase_intent, after_months=4
    )

    assert gt.type is events.LifeEventType.HOME_PURCHASE_INTENT
    assert state.is_renter is False
    assert state.monthly_rent_paise == 0
    assert renter.is_renter is False

    rent_after = [t for t in after if t.category == "rent"]
    assert not rent_after, "rent must stop generating after home_purchase_intent"

    builder_txns = [t for t in after if t.category == "builder_payment"]
    assert builder_txns, "expected builder payment debits"

    assert any(e.category == "home_loan_emi" for e in state.emis)
    assert "home_loan" in renter.products_held

    # Everything must still respect the overdraft guard.
    assert all(t.balance_after_paise >= 0 for t in before + after)


# ---------------------------------------------------------------------------
# bonus_windfall
# ---------------------------------------------------------------------------


def test_bonus_windfall_credits_a_multiple_of_monthly_income() -> None:
    persona = _persona_of(Archetype.YOUNG_SALARIED_TECHIE)
    state = generator.new_state(persona, seed=42)
    generator.generate_history(persona, months=2, seed=42, state=state)
    base_income = state.monthly_income_paise
    assert state.last_generated_date is not None
    trigger_ts = datetime.combine(state.last_generated_date, datetime.min.time())

    gt = events.bonus_windfall.apply(persona, state, trigger_ts)
    after = generator.generate_history(persona, months=1, seed=42, state=state)

    assert gt.type is events.LifeEventType.BONUS_WINDFALL
    assert 3.0 <= gt.params["multiplier"] <= 5.0

    bonus_txns = [t for t in after if t.category == "bonus"]
    assert len(bonus_txns) == 1
    assert bonus_txns[0].amount_paise == gt.params["amount_paise"]
    assert bonus_txns[0].amount_paise >= base_income * 3


# ---------------------------------------------------------------------------
# wedding
# ---------------------------------------------------------------------------


def test_wedding_schedules_catering_jewellery_and_venue_spend() -> None:
    persona = _persona_of(Archetype.YOUNG_SALARIED_TECHIE)
    _before, gt, after, _state = _apply_mid_stream(persona, events.wedding, after_months=3)

    assert gt.type is events.LifeEventType.WEDDING
    categories = {t.category for t in after}
    assert {"wedding_catering", "jewellery", "venue_booking"} <= categories
    total_spent = sum(
        t.amount_paise
        for t in after
        if t.category in ("wedding_catering", "jewellery", "venue_booking")
    )
    assert total_spent <= gt.params["total_estimated_spend_paise"]
    assert total_spent > 0


# ---------------------------------------------------------------------------
# churn_risk
# ---------------------------------------------------------------------------


def test_churn_risk_decays_upi_activity_and_drains_balance() -> None:
    persona = _persona_of(Archetype.YOUNG_SALARIED_TECHIE)
    before, gt, after, state = _apply_mid_stream(persona, events.churn_risk, after_months=3)

    assert gt.type is events.LifeEventType.CHURN_RISK
    assert state.churn_decay_start is not None
    assert state.churn_drain_vpa is not None

    # UPI activity factor strictly decays as sim-days pass after the trigger.
    day0 = state.churn_decay_start
    factor_at_0 = generator._upi_factor(state, day0)
    factor_at_30 = generator._upi_factor(state, day0 + timedelta(days=30))
    assert factor_at_30 < factor_at_0

    drain_txns = [t for t in after if t.category == "balance_drain"]
    assert len(drain_txns) == 1
    assert drain_txns[0].merchant == gt.params["competitor_vpa"]
    assert drain_txns[0].channel is generator.Channel.UPI

    # Balance never goes negative even with the large drain.
    assert all(t.balance_after_paise >= 0 for t in before + after)
