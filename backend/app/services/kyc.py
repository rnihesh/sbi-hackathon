"""Simulated KYC verifier with realistic behaviour.

Real, deterministic logic - never random at runtime:
- PAN format validation (``ABCDE1234F``).
- Aadhaar: 12 digits + **Verhoeff** checksum (the real Aadhaar check-digit
  scheme), so made-up numbers fail like they would against UIDAI.
- Fuzzy name matching (claimed vs official).
- A deterministic ~5% "manual review / mismatch" injection keyed on a hash of
  the inputs, plus a small simulated verification latency - reproducible, so
  the same applicant always gets the same outcome (no runtime ``random``).
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
_AADHAAR_RE = re.compile(r"^\d{12}$")

# ---------------------------------------------------------------------------
# Verhoeff checksum (the scheme Aadhaar actually uses)
# ---------------------------------------------------------------------------
_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 9, 1, 6, 7, 4, 3, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)
_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)


def _verhoeff_checksum(number: str) -> int:
    c = 0
    for i, item in enumerate(reversed(number)):
        c = _D[c][_P[i % 8][int(item)]]
    return c


def verhoeff_check_digit(number_without_check: str) -> int:
    """Return the Verhoeff check digit for ``number_without_check``.

    Helper for constructing valid Aadhaar-style numbers (used by tests/seeds):
    ``full = number_without_check + str(verhoeff_check_digit(number_without_check))``.
    """
    c = 0
    for i, item in enumerate(reversed(number_without_check)):
        c = _D[c][_P[(i + 1) % 8][int(item)]]
    return _INV[c]


def validate_pan(pan: str) -> bool:
    """True if ``pan`` matches the PAN format ``ABCDE1234F``."""
    return bool(PAN_RE.match(pan.strip().upper()))


def validate_aadhaar(aadhaar: str) -> bool:
    """True if ``aadhaar`` is 12 digits with a valid Verhoeff checksum."""
    digits = aadhaar.replace(" ", "").strip()
    if not _AADHAAR_RE.match(digits):
        return False
    if digits[0] in "01":  # UIDAI Aadhaar never starts with 0 or 1
        return False
    return _verhoeff_checksum(digits) == 0


def name_match_score(claimed: str, official: str) -> float:
    """Fuzzy 0..1 similarity between a claimed name and an official name.

    Order-insensitive (token-sorted) with a raw-sequence fallback, so
    "Rahul Kumar Sharma" vs "Sharma Rahul" still scores high.
    """
    def norm(s: str) -> str:
        return re.sub(r"[^a-z ]", "", s.lower()).strip()

    a, b = norm(claimed), norm(official)
    if not a or not b:
        return 0.0
    sorted_a = " ".join(sorted(a.split()))
    sorted_b = " ".join(sorted(b.split()))
    token_ratio = SequenceMatcher(None, sorted_a, sorted_b).ratio()
    raw_ratio = SequenceMatcher(None, a, b).ratio()
    return round(max(token_ratio, raw_ratio), 3)


class KycStatus(StrEnum):
    VERIFIED = "verified"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


@dataclass(slots=True)
class KycResult:
    status: KycStatus
    pan_valid: bool
    aadhaar_valid: bool | None
    name_match: float | None
    latency_ms: int
    reason: str

    @property
    def verified(self) -> bool:
        return self.status is KycStatus.VERIFIED

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "pan_valid": self.pan_valid,
            "aadhaar_valid": self.aadhaar_valid,
            "name_match": self.name_match,
            "latency_ms": self.latency_ms,
            "reason": self.reason,
        }


_NAME_MATCH_THRESHOLD = 0.6


def _injection_bucket(*parts: str) -> int:
    """Deterministic 0..99 bucket from a hash of the inputs (never random)."""
    joined = "|".join(p.strip().upper() for p in parts if p)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


async def verify(
    *,
    name: str,
    pan: str,
    aadhaar: str | None = None,
    official_name: str | None = None,
    simulate_latency: bool = True,
) -> KycResult:
    """Verify an applicant's KYC. Deterministic, reproducible outcome.

    ``simulate_latency`` (default on) sleeps a small, input-derived delay to
    mimic a real verifier round-trip; tests pass ``False`` to run instantly.
    """
    pan_valid = validate_pan(pan)
    aadhaar_valid: bool | None = validate_aadhaar(aadhaar) if aadhaar is not None else None
    name_match = name_match_score(name, official_name) if official_name else None

    bucket = _injection_bucket(name, pan, aadhaar or "")
    # ~5% of otherwise-clean applicants get held back for manual review / mismatch.
    injected_review = bucket < 3
    injected_fail = 3 <= bucket < 5
    latency_ms = 40 + bucket % 60 + (200 if bucket < 5 else 0)

    if simulate_latency:
        await asyncio.sleep(latency_ms / 1000)

    if not pan_valid:
        status, reason = KycStatus.FAILED, "PAN format invalid (expected ABCDE1234F)"
    elif aadhaar is not None and not aadhaar_valid:
        status, reason = KycStatus.FAILED, "Aadhaar failed checksum validation"
    elif name_match is not None and name_match < _NAME_MATCH_THRESHOLD:
        status, reason = (
            KycStatus.NEEDS_REVIEW,
            f"name mismatch with records (score {name_match:.2f})",
        )
    elif injected_fail:
        status, reason = KycStatus.FAILED, "verification declined by bureau (simulated)"
    elif injected_review:
        status, reason = KycStatus.NEEDS_REVIEW, "flagged for manual review (random sample)"
    else:
        status, reason = KycStatus.VERIFIED, "identity verified"

    return KycResult(
        status=status,
        pan_valid=pan_valid,
        aadhaar_valid=aadhaar_valid,
        name_match=name_match,
        latency_ms=latency_ms,
        reason=reason,
    )
