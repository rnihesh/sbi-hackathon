"""LLM pricing table and cost computation (USD).

Prices are approximate USD per 1,000,000 tokens (input, output). Keep this dict
updatable - bump entries as provider pricing changes.
"""

from __future__ import annotations

from decimal import Decimal

_MILLION = Decimal("1000000")

# model id -> (usd_per_1M_input, usd_per_1M_output)
PRICING: dict[str, tuple[Decimal, Decimal]] = {
    # OpenAI
    "gpt-4.1": (Decimal("2.00"), Decimal("8.00")),
    "gpt-4.1-mini": (Decimal("0.40"), Decimal("1.60")),
    "gpt-4.1-nano": (Decimal("0.10"), Decimal("0.40")),
    "gpt-4o": (Decimal("2.50"), Decimal("10.00")),
    "gpt-4o-mini": (Decimal("0.15"), Decimal("0.60")),
    # Google Gemini
    "gemini-2.5-pro": (Decimal("1.25"), Decimal("10.00")),
    "gemini-2.5-flash": (Decimal("0.30"), Decimal("2.50")),
    "gemini-2.5-flash-lite": (Decimal("0.10"), Decimal("0.40")),
    # Anthropic
    "claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00")),
    "claude-sonnet-4-6": (Decimal("3.00"), Decimal("15.00")),
    "claude-sonnet-5": (Decimal("3.00"), Decimal("15.00")),
    "claude-opus-4-8": (Decimal("5.00"), Decimal("25.00")),
    "claude-3-5-haiku-latest": (Decimal("0.80"), Decimal("4.00")),
}


def _lookup(model: str) -> tuple[Decimal, Decimal] | None:
    """Resolve pricing for a model id, tolerating provider-decorated ids.

    Providers echo back dated or prefixed variants of the requested id
    (e.g. OpenAI returns ``gpt-4o-2024-08-06`` for ``gpt-4o``, Gemini may
    prefix ``models/``). Match exact first, then the longest known id that
    prefixes the reported one.
    """
    exact = PRICING.get(model)
    if exact is not None:
        return exact
    normalized = model.removeprefix("models/")
    exact = PRICING.get(normalized)
    if exact is not None:
        return exact
    candidates = [known for known in PRICING if normalized.startswith(known)]
    if not candidates:
        return None
    return PRICING[max(candidates, key=len)]


def compute_cost(model: str, tokens_in: int, tokens_out: int) -> Decimal:
    """Return the USD cost of a call. Unknown models cost ``Decimal('0')``."""
    prices = _lookup(model)
    if prices is None:
        return Decimal("0")
    price_in, price_out = prices
    cost = (Decimal(tokens_in) * price_in + Decimal(tokens_out) * price_out) / _MILLION
    # 6 dp is plenty for per-call cost tracking.
    return cost.quantize(Decimal("0.000001"))
