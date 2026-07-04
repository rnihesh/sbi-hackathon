"""Multilingual compliance hardening for the deterministic PolicyEngine.

A reply written entirely in a native script (Devanagari, Telugu, Tamil, ...)
must still trip the same disclosure and blocked-claim gates an English reply
would. These are pure string checks - no LLM calls, per the budget rule.
"""

from __future__ import annotations

import pytest

from app.agents import compliance_terms
from app.agents.guardrails import _INSURANCE_DISCLOSURE, _MF_DISCLOSURE, PolicyEngine

# Full profile so the suitability gate never fires and we isolate the
# disclosure / blocked-claim behaviour under test.
_SUITABLE = {"income": 900_000, "risk": "high"}

# Every supported non-English language: a natural sentence that names an
# investment product, mapped to its language for readable failure output.
_INVESTMENT_SENTENCES: dict[str, str] = {
    "hindi": "म्यूचुअल फंड में निवेश करना एक अच्छा विकल्प है।",
    "telugu": "మ్యూచువల్ ఫండ్‌లో పెట్టుబడి పెట్టడం మంచి ఎంపిక.",
    "tamil": "மியூச்சுவல் ஃபண்டில் முதலீடு செய்வது ஒரு நல்ல தேர்வு.",
    "kannada": "ಮ್ಯೂಚುವಲ್ ಫಂಡ್‌ನಲ್ಲಿ ಹೂಡಿಕೆ ಮಾಡುವುದು ಒಳ್ಳೆಯ ಆಯ್ಕೆ.",
    "bengali": "মিউচুয়াল ফান্ডে বিনিয়োগ করা একটি ভালো বিকল্প।",
    "marathi": "म्युच्युअल फंडात गुंतवणूक करणे हा एक चांगला पर्याय आहे.",
    "hinglish": "Har mahine thoda nivesh karke aap paisa badha sakte hain.",
}

_INSURANCE_SENTENCES: dict[str, str] = {
    "hindi": "जीवन बीमा आपके परिवार की सुरक्षा करता है।",
    "telugu": "జీవిత బీమా మీ కుటుంబాన్ని రక్షిస్తుంది.",
    "tamil": "ஆயுள் காப்பீடு உங்கள் குடும்பத்தைப் பாதுகாக்கிறது.",
    "kannada": "ಜೀವ ವಿಮೆ ನಿಮ್ಮ ಕುಟುಂಬವನ್ನು ರಕ್ಷಿಸುತ್ತದೆ.",
    "bengali": "জীবন বীমা আপনার পরিবারকে সুরক্ষা দেয়।",
    "marathi": "जीवन विमा तुमच्या कुटुंबाचे संरक्षण करतो.",
    "hinglish": "Jeevan bima aapke parivaar ko surksha deta hai.",
}

# (sentence, the exact bad phrase that must be neutralised out of the reply).
_BLOCKED_CLAIM_SENTENCES: dict[str, tuple[str, str]] = {
    "hindi": ("इस योजना में गारंटीड रिटर्न मिलता है।", "गारंटीड रिटर्न"),
    "telugu": ("ఈ ప్లాన్‌లో గ్యారంటీడ్ రిటర్న్ ఉంటుంది.", "గ్యారంటీడ్ రిటర్న్"),
    "tamil": ("இந்த திட்டத்தில் கேரண்டீட் ரிட்டர்ன் உண்டு.", "கேரண்டீட் ரிட்டர்ன்"),
    "kannada": ("ಈ ಯೋಜನೆಯಲ್ಲಿ ಗ್ಯಾರಂಟೀಡ್ ರಿಟರ್ನ್ ಇದೆ.", "ಗ್ಯಾರಂಟೀಡ್ ರಿಟರ್ನ್"),
    "bengali": ("এই প্ল্যানে গ্যারান্টিড রিটার্ন পাওয়া যায়।", "গ্যারান্টিড রিটার্ন"),
    "marathi": ("या योजनेत गॅरंटीड परतावा मिळतो.", "गॅरंटीड परतावा"),
    "hinglish": ("Is plan mein guaranteed munafa milta hai.", "guaranteed munafa"),
}

# Native "no/zero risk" claims -> must be flagged and softened.
_ZERO_RISK_SENTENCES: dict[str, tuple[str, str]] = {
    "hindi": ("इसमें कोई जोखिम नहीं है।", "कोई जोखिम नहीं"),
    "telugu": ("దీనిలో జీరో రిస్క్ ఉంది.", "జీరో రిస్క్"),
    "tamil": ("இதில் ஜீரோ ரிஸ்க் மட்டுமே.", "ஜீரோ ரிஸ்க்"),
    "kannada": ("ಇದರಲ್ಲಿ ಜೀರೋ ರಿಸ್ಕ್ ಇದೆ.", "ಜೀರೋ ರಿಸ್ಕ್"),
    "bengali": ("এতে জিরো রিস্ক আছে।", "জিরো রিস্ক"),
    "marathi": ("यात झिरो रिस्क आहे.", "झिरो रिस्क"),
    "hinglish": ("Ismein koi risk nahi hai.", "koi risk nahi"),
}


# ---------------------------------------------------------------------------
# Investment disclosure across every language
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("language", sorted(_INVESTMENT_SENTENCES))
def test_native_investment_sentence_triggers_mf_disclosure(language: str) -> None:
    policy = PolicyEngine()
    verdict = policy.check(_INVESTMENT_SENTENCES[language], profile=_SUITABLE)

    assert _MF_DISCLOSURE in verdict.fixed_text, language
    assert "mutual_fund" in verdict.disclosures_added, language
    # The disclosure must append on its own paragraph, never mid-sentence.
    assert verdict.fixed_text.startswith(_INVESTMENT_SENTENCES[language]), language
    # An investment mention must not drag in the insurance disclosure.
    assert _INSURANCE_DISCLOSURE not in verdict.fixed_text, language


@pytest.mark.parametrize("language", sorted(_INSURANCE_SENTENCES))
def test_native_insurance_sentence_triggers_insurance_disclosure(language: str) -> None:
    policy = PolicyEngine()
    verdict = policy.check(_INSURANCE_SENTENCES[language], profile=_SUITABLE)

    assert _INSURANCE_DISCLOSURE in verdict.fixed_text, language
    assert "insurance" in verdict.disclosures_added, language
    assert _MF_DISCLOSURE not in verdict.fixed_text, language


# ---------------------------------------------------------------------------
# Blocked claims across every language
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("language", sorted(_BLOCKED_CLAIM_SENTENCES))
def test_native_guaranteed_returns_claim_is_blocked(language: str) -> None:
    sentence, bad_phrase = _BLOCKED_CLAIM_SENTENCES[language]
    policy = PolicyEngine()
    verdict = policy.check(sentence, profile=_SUITABLE)

    assert not verdict.allowed, language
    assert any("blocked_claim" in v for v in verdict.violations), language
    # The offending guarantee must be gone from the reply we would send.
    assert bad_phrase not in verdict.fixed_text, language


@pytest.mark.parametrize("language", sorted(_ZERO_RISK_SENTENCES))
def test_native_zero_risk_claim_is_blocked(language: str) -> None:
    sentence, bad_phrase = _ZERO_RISK_SENTENCES[language]
    policy = PolicyEngine()
    verdict = policy.check(sentence, profile=_SUITABLE)

    assert not verdict.allowed, language
    assert any("blocked_claim" in v for v in verdict.violations), language
    assert bad_phrase not in verdict.fixed_text, language


# ---------------------------------------------------------------------------
# Specificity: unrelated native text must stay untouched
# ---------------------------------------------------------------------------


def test_plain_native_greeting_adds_no_disclosure() -> None:
    policy = PolicyEngine()
    # "Hello, how can I help you with your account today?" in Hindi - no
    # regulated product named.
    greeting = "नमस्ते, मैं आपके खाते में कैसे मदद कर सकता हूँ?"
    verdict = policy.check(greeting, profile=_SUITABLE)

    assert verdict.fixed_text == greeting
    assert verdict.disclosures_added == []
    assert verdict.allowed


# ---------------------------------------------------------------------------
# English behaviour is unchanged (regression guard)
# ---------------------------------------------------------------------------


def test_english_investment_still_triggers_disclosure() -> None:
    policy = PolicyEngine()
    verdict = policy.check(
        "A mutual fund SIP can help you grow wealth.", profile=_SUITABLE
    )
    assert _MF_DISCLOSURE in verdict.fixed_text
    assert "mutual_fund" in verdict.disclosures_added


def test_english_blocked_claims_still_rewritten() -> None:
    policy = PolicyEngine()
    verdict = policy.check("This gives guaranteed returns with zero risk!")
    assert not verdict.allowed
    assert "guaranteed returns" not in verdict.fixed_text.lower()
    assert "zero risk" not in verdict.fixed_text.lower()


def test_english_non_regulated_text_is_untouched() -> None:
    policy = PolicyEngine()
    text = "Your account balance is up to date and your card is active."
    verdict = policy.check(text, profile=_SUITABLE)
    assert verdict.fixed_text == text
    assert verdict.disclosures_added == []
    assert verdict.allowed


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def test_every_supported_language_has_investment_and_insurance_terms() -> None:
    from app.agents.language import SUPPORTED_LANGUAGES

    for lang in SUPPORTED_LANGUAGES:
        assert compliance_terms.INVESTMENT_TERMS_BY_LANGUAGE.get(lang), lang
        assert compliance_terms.INSURANCE_TERMS_BY_LANGUAGE.get(lang), lang


def test_mentions_helpers_are_case_insensitive_for_latin() -> None:
    assert compliance_terms.mentions_investment("MUTUAL FUND")
    assert compliance_terms.mentions_insurance("INSURANCE")
    assert not compliance_terms.mentions_investment("just a friendly chat")


def test_no_em_dash_in_any_native_term_or_replacement() -> None:
    em_dash = chr(0x2014)
    for terms in compliance_terms.INVESTMENT_TERMS_BY_LANGUAGE.values():
        assert all(em_dash not in t for t in terms)
    for terms in compliance_terms.INSURANCE_TERMS_BY_LANGUAGE.values():
        assert all(em_dash not in t for t in terms)
    for claims in compliance_terms.NATIVE_BLOCKED_CLAIMS_BY_LANGUAGE.values():
        for phrase, replacement in claims:
            assert em_dash not in phrase
            assert em_dash not in replacement
