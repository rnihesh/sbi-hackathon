"""Deterministic domain services - the prototype's "core banking".

These are plain, real logic against the real database (no LLM, no randomness at
runtime). Agents call them as tools; the API layer calls them directly. Keeping
all money/eligibility/KYC logic here (not in prompts) is what makes the agent
mesh trustworthy: the LLM decides *what* to do, these services decide *whether
it is allowed* and *what actually happens*.
"""

from __future__ import annotations

from app.services import kyc, ledger, products

__all__ = ["kyc", "ledger", "products"]
