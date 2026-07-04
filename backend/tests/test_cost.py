"""Tests for the LLM cost table and computation."""

from __future__ import annotations

from decimal import Decimal

from app.llm.cost import PRICING, compute_cost


def test_compute_cost_known_model() -> None:
    # gpt-4o-mini: $0.15/1M in, $0.60/1M out
    cost = compute_cost("gpt-4o-mini", tokens_in=1_000_000, tokens_out=1_000_000)
    assert cost == Decimal("0.750000")


def test_compute_cost_partial_tokens() -> None:
    # 500k in @ 0.15, 250k out @ 0.60 -> 0.075 + 0.15 = 0.225
    cost = compute_cost("gpt-4o-mini", tokens_in=500_000, tokens_out=250_000)
    assert cost == Decimal("0.225000")


def test_compute_cost_zero_tokens() -> None:
    assert compute_cost("gpt-4.1", 0, 0) == Decimal("0.000000")


def test_compute_cost_unknown_model_is_zero() -> None:
    assert compute_cost("no-such-model", 1000, 1000) == Decimal("0")


def test_every_default_model_priced() -> None:
    # Sanity: the config defaults must all appear in the pricing table.
    for model in ("gpt-4.1", "gpt-4.1-mini", "gemini-2.5-pro", "gemini-2.5-flash",
                  "claude-haiku-4-5", "claude-sonnet-4-6"):
        assert model in PRICING, model
