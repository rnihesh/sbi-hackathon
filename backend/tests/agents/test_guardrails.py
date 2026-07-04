"""Guardrail tests: PII redaction, policy engine, hash-chained audit."""

from __future__ import annotations

import sqlalchemy as sa

from app.agents.guardrails import _MF_DISCLOSURE, AuditTrail, PIIRedactor, PolicyEngine
from app.models.audit import AuditLog

# ---------------------------------------------------------------------------
# PII redaction
# ---------------------------------------------------------------------------


def test_redacts_pan_aadhaar_phone_email_and_is_reversible() -> None:
    redactor = PIIRedactor()
    text = (
        "My PAN is ABCDE1234F, Aadhaar 1234 5678 9012, "
        "call +91 9876543210 or email rahul.sharma@example.com"
    )
    result = redactor.redact(text)

    # Raw PII must be gone; typed placeholders present.
    assert "ABCDE1234F" not in result.text
    assert "9876543210" not in result.text
    assert "rahul.sharma@example.com" not in result.text
    assert "1234 5678 9012" not in result.text
    assert "<PAN_1>" in result.text
    assert "<PHONE_1>" in result.text
    assert "<EMAIL_1>" in result.text
    assert "<AADHAAR_1>" in result.text

    # Fully reversible.
    assert result.restore(result.text) == text


def test_redaction_dedupes_repeated_values() -> None:
    redactor = PIIRedactor()
    result = redactor.redact("PAN ABCDE1234F again ABCDE1234F")
    assert result.text.count("<PAN_1>") == 2
    assert len(result.mapping) == 1


def test_restore_args_restores_only_string_values() -> None:
    redactor = PIIRedactor()
    result = redactor.redact("my pan is ABCDE1234F")
    placeholder = next(iter(result.mapping))
    restored = result.restore_args({"value": placeholder, "count": 3})
    assert restored["value"] == "ABCDE1234F"
    assert restored["count"] == 3


# ---------------------------------------------------------------------------
# Policy engine
# ---------------------------------------------------------------------------


def test_appends_mutual_fund_disclosure() -> None:
    policy = PolicyEngine()
    verdict = policy.check(
        "A mutual fund SIP can help you grow wealth.",
        profile={"income": 900000, "risk": "high"},
    )
    assert "market risks" in verdict.fixed_text.lower()
    assert "mutual_fund" in verdict.disclosures_added


def test_blocks_guaranteed_returns_and_zero_risk() -> None:
    policy = PolicyEngine()
    verdict = policy.check("This gives guaranteed returns with zero risk!")
    assert not verdict.allowed
    assert any("blocked_claim" in v for v in verdict.violations)
    assert "guaranteed returns" not in verdict.fixed_text.lower()
    assert "zero risk" not in verdict.fixed_text.lower()


def test_suitability_gate_blocks_without_income_and_risk() -> None:
    policy = PolicyEngine()
    verdict = policy.check("You should invest in a mutual fund SIP now.", profile={})
    assert any("suitability_gate" in v for v in verdict.violations)
    assert "suitability check" in verdict.fixed_text.lower()
    assert not verdict.allowed


def test_suitability_gate_passes_with_full_profile() -> None:
    policy = PolicyEngine()
    verdict = policy.check(
        "You should invest in a mutual fund SIP now.",
        profile={"income": 1_200_000, "risk": "medium"},
    )
    assert not any("suitability_gate" in v for v in verdict.violations)
    # disclosure still appended
    assert "market risks" in verdict.fixed_text.lower()


def test_disclosure_appends_cleanly_after_a_non_english_reply() -> None:
    """Vernacular compatibility: the disclosure engine is string-based and
    English-only - it must still just APPEND, on its own blank line, never
    mangle or mid-sentence-glue onto a non-English draft (Hindi here)."""
    policy = PolicyEngine()
    hindi_reply = (
        "Aap is mutual fund SIP mein invest karke apna paisa badha sakte hain."
    )
    verdict = policy.check(hindi_reply, profile={"income": 900000, "risk": "high"})

    assert verdict.fixed_text.startswith(hindi_reply)
    # A real paragraph break, not a bare space glued onto the last word - the
    # English disclosure must never mash into the vernacular sentence above it.
    assert f"{hindi_reply}\n\n" in verdict.fixed_text
    assert hindi_reply + " " + _MF_DISCLOSURE not in verdict.fixed_text
    assert "market risks" in verdict.fixed_text
    assert "mutual_fund" in verdict.disclosures_added


def test_disclosure_appends_cleanly_after_a_devanagari_script_reply() -> None:
    """Same joiner check, but with actual Devanagari script - the disclosure
    engine only detects English-literal keywords ("mutual fund", "SIP", the
    terms Hindi banking chat commonly keeps in Latin script anyway), so those
    stay untranslated in the draft while the rest of the sentence is Hindi."""
    policy = PolicyEngine()
    devanagari_reply = (
        "अगर आप हर महीने थोड़ा निवेश करना चाहते हैं तो एक SIP mutual fund "
        "अच्छा विकल्प है."
    )
    verdict = policy.check(devanagari_reply, profile={"income": 900000, "risk": "high"})

    assert verdict.fixed_text.startswith(f"{devanagari_reply}\n\n")
    assert _MF_DISCLOSURE in verdict.fixed_text


# ---------------------------------------------------------------------------
# Audit hash chain
# ---------------------------------------------------------------------------


async def test_audit_chain_verifies_and_detects_tamper(db) -> None:  # type: ignore[no-untyped-def]
    audit = AuditTrail()
    r1 = await audit.record(db, "system", "a.created", "thing", "1", {"x": 1})
    r2 = await audit.record(db, "system", "b.created", "thing", "2", {"y": 2})
    r3 = await audit.record(db, "system", "c.created", "thing", "3", {"z": 3})
    await db.commit()

    # Chain links correctly.
    assert r2.prev_hash == r1.hash
    assert r3.prev_hash == r2.hash
    assert await AuditTrail.verify(db) is True

    # Tamper with a committed payload → verification fails.
    row = await db.scalar(sa.select(AuditLog).where(AuditLog.entity_id == "2"))
    row.payload = {"y": 999}
    await db.commit()
    assert await AuditTrail.verify(db) is False
