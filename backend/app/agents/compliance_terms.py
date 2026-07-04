"""Multilingual compliance term tables for the deterministic policy engine.

The :class:`~app.agents.guardrails.PolicyEngine` decides whether an outbound
reply mentions a *regulated* product - and therefore needs a mandated
disclosure - by substring-matching a table of trigger terms, and it neutralises
disallowed marketing claims ("guaranteed returns", "zero risk") the same way.
Those tables were originally English-only, so a reply written entirely in a
native script (Devanagari, Telugu, Tamil, ...) could name a mutual fund or an
insurance policy and silently skip the disclosure, or promise "guaranteed
returns" in Hindi and dodge the block.

Compliance has to stay deterministic (never an LLM call, per the budget rule),
so the fix is not translation-at-runtime but a static, reviewed vocabulary: the
native-script banking terms for each supported language, kept here as
per-language dicts. Matching is normalised with ``str.casefold`` (a no-op for
the Indic scripts, which are caseless, but it keeps English/Hinglish matching
case-insensitive) and is plain substring containment.

Scope and honesty notes
------------------------
- Only the two categories the engine actually issues a disclosure for are wired
  to trigger one: ``investment`` (the market-linked / securities vocabulary ->
  the SEBI market-risk disclosure) and ``insurance`` (-> the IRDAI solicitation
  disclosure).
- Fixed deposits and loans are regulated products too, but neither the
  market-risk nor the insurance disclosure is *true* of them (an FD is not
  market-linked; a loan is neither). Appending a mutual-fund risk line to an
  FD-only reply would itself be a misstatement, so those terms are deliberately
  NOT wired as investment triggers. "Guaranteed profit" style claims about any
  product are still caught, via the blocked-claims table below.
- Terms are standard Indian retail-banking vocabulary (the transliterated
  loanwords SBI and peers actually use in vernacular copy, e.g. "म्यूचुअल फंड",
  plus the native words where they are the common register, e.g. "निवेश",
  "बीमा"). They were authored by hand from domain knowledge, not machine
  translated; a native-speaker pass before GA is still worthwhile, but every
  entry errs toward *over*-detection, which is the safe direction for a
  disclosure gate.

English behaviour is unchanged: the English tables are carried over verbatim
and native terms only ever *add* matches, never remove them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# ===========================================================================
# Investment (market-linked / securities) vocabulary, per language.
#   Mentions of any of these append the mutual-fund market-risk disclosure.
# ===========================================================================

INVESTMENT_TERMS_BY_LANGUAGE: dict[str, tuple[str, ...]] = {
    # Carried over verbatim from the original English-only keyword tuple.
    "english": (
        "mutual fund",
        "mutual funds",
        " sip",
        "sip ",
        "equity",
        "market-linked",
        "market linked",
        "elss",
        "portfolio",
        "wealth",
        "invest",
    ),
    # Hinglish (Latin script): only the transliterated words English does not
    # already cover - "invest"/"sip"/"mutual fund" above already catch the rest.
    "hinglish": (
        "nivesh",
        "share bazaar",
        "share market",
    ),
    "hindi": (
        "म्यूचुअल फंड",
        "म्यूचुअल फ़ंड",
        "निवेश",
        "इक्विटी",
        "शेयर बाज़ार",
        "शेयर बाजार",
        "शेयर मार्केट",
        "शेयर",
        "स्टॉक",
        "एसआईपी",
    ),
    "telugu": (
        "మ్యూచువల్ ఫండ్",
        "పెట్టుబడి",
        "ఈక్విటీ",
        "షేర్ మార్కెట్",
        "షేర్లు",
        "షేర్",
        "స్టాక్",
        "ఎస్ఐపీ",
    ),
    "tamil": (
        "மியூச்சுவல் ஃபண்ட்",
        "பரஸ்பர நிதி",
        "முதலீடு",
        "பங்குச் சந்தை",
        "பங்கு",
        "ஈக்விட்டி",
        "ஸ்டாக்",
        "எஸ்ஐபி",
    ),
    "kannada": (
        "ಮ್ಯೂಚುವಲ್ ಫಂಡ್",
        "ಹೂಡಿಕೆ",
        "ಷೇರು ಮಾರುಕಟ್ಟೆ",
        "ಷೇರು",
        "ಸ್ಟಾಕ್",
        "ಈಕ್ವಿಟಿ",
        "ಎಸ್ಐಪಿ",
    ),
    "bengali": (
        "মিউচুয়াল ফান্ড",
        "বিনিয়োগ",
        "শেয়ার বাজার",
        "শেয়ার",
        "স্টক",
        "ইকুইটি",
        "এসআইপি",
    ),
    "marathi": (
        "म्युच्युअल फंड",
        "गुंतवणूक",
        "शेअर बाजार",
        "शेअर",
        "स्टॉक",
        "इक्विटी",
        "एसआयपी",
    ),
}

# ===========================================================================
# Insurance vocabulary, per language.
#   Mentions of any of these append the insurance-solicitation disclosure.
# ===========================================================================

INSURANCE_TERMS_BY_LANGUAGE: dict[str, tuple[str, ...]] = {
    "english": (
        "insurance",
        "term plan",
        "life cover",
        "policy premium",
        "accident cover",
    ),
    "hinglish": (
        "bima",
        "jeevan bima",
    ),
    "hindi": (
        "बीमा",
        "जीवन बीमा",
        "टर्म प्लान",
        "इंश्योरेंस",
        "इन्शुरन्स",
    ),
    "telugu": (
        "బీమా",
        "జీవిత బీమా",
        "ఇన్సూరెన్స్",
        "టర్మ్ ప్లాన్",
    ),
    "tamil": (
        "காப்பீடு",
        "ஆயுள் காப்பீடு",
        "இன்சூரன்ஸ்",
        "டர்ம் பிளான்",
    ),
    "kannada": (
        "ವಿಮೆ",
        "ಜೀವ ವಿಮೆ",
        "ಇನ್ಶೂರೆನ್ಸ್",
        "ಟರ್ಮ್ ಪ್ಲಾನ್",
    ),
    "bengali": (
        "বীমা",
        "জীবন বীমা",
        "ইন্স্যুরেন্স",
        "টার্ম প্ল্যান",
    ),
    "marathi": (
        "विमा",
        "जीवन विमा",
        "इन्शुरन्स",
        "टर्म प्लॅन",
    ),
}


# ===========================================================================
# Disallowed marketing claims -> compliant rewrite, per language.
#   The two worst families: "guaranteed / assured returns (or profit)" and
#   "zero / no risk". English entries are regex sources (whitespace-tolerant);
#   native entries are literal phrases (escaped when compiled).
# ===========================================================================

# English: kept verbatim as regex sources so behaviour is byte-for-byte stable.
_ENGLISH_BLOCKED_CLAIMS: tuple[tuple[str, str], ...] = (
    (r"guaranteed\s+returns?", "potential returns (subject to market risk)"),
    (r"assured\s+returns?", "indicative returns (not assured)"),
    (r"guaranteed\s+profits?", "possible gains (not guaranteed)"),
    (r"zero[\s\-]*risk", "lower-risk"),
    (r"risk[\s\-]*free", "lower-risk"),
    (r"\bno\s+risk\b", "reduced risk"),
    (r"100%\s*safe", "designed to be low-risk"),
    (r"\bdouble\s+your\s+money\b", "grow your money over time"),
)

# Native (and Hinglish) blocked claims: literal bad phrase -> compliant rewrite.
# Rewrites stay short and standard so the corrected sentence still reads
# naturally in the same language; each removes the guarantee / softens the
# risk claim. The mandated (English) disclosure is still appended separately.
NATIVE_BLOCKED_CLAIMS_BY_LANGUAGE: dict[str, tuple[tuple[str, str], ...]] = {
    # Hinglish (Latin) transliterations English regex does not already catch.
    "hinglish": (
        ("guaranteed munafa", "possible returns (subject to market risk)"),
        ("pakka munafa", "possible returns (subject to market risk)"),
        ("pakka return", "possible returns (subject to market risk)"),
        ("koi risk nahi", "lower risk"),
        ("koi jokhim nahi", "lower risk"),
    ),
    "hindi": (
        ("गारंटीड रिटर्न्स", "संभावित रिटर्न (बाज़ार जोखिम के अधीन)"),
        ("गारंटीड रिटर्न", "संभावित रिटर्न (बाज़ार जोखिम के अधीन)"),
        ("गारंटीड मुनाफ़ा", "संभावित मुनाफ़ा (गारंटी नहीं)"),
        ("गारंटीड मुनाफा", "संभावित मुनाफ़ा (गारंटी नहीं)"),
        ("पक्का मुनाफ़ा", "संभावित मुनाफ़ा (गारंटी नहीं)"),
        ("पक्का रिटर्न", "संभावित रिटर्न (बाज़ार जोखिम के अधीन)"),
        ("कोई जोखिम नहीं", "कम जोखिम"),
        ("कोई रिस्क नहीं", "कम जोखिम"),
        ("ज़ीरो रिस्क", "कम जोखिम"),
        ("जीरो रिस्क", "कम जोखिम"),
    ),
    "telugu": (
        ("గ్యారంటీడ్ రిటర్న్", "సంభావ్య రాబడి (మార్కెట్ రిస్క్‌కు లోబడి)"),
        ("గ్యారంటీ రాబడి", "సంభావ్య రాబడి (మార్కెట్ రిస్క్‌కు లోబడి)"),
        ("హామీ రాబడి", "సంభావ్య రాబడి (మార్కెట్ రిస్క్‌కు లోబడి)"),
        ("జీరో రిస్క్", "తక్కువ రిస్క్"),
        ("రిస్క్ లేదు", "తక్కువ రిస్క్"),
    ),
    "tamil": (
        ("கேரண்டீட் ரிட்டர்ன்", "சாத்தியமான வருமானம் (சந்தை அபாயத்துக்கு உட்பட்டது)"),
        ("உறுதியான வருமானம்", "சாத்தியமான வருமானம் (சந்தை அபாயத்துக்கு உட்பட்டது)"),
        ("ஜீரோ ரிஸ்க்", "குறைந்த அபாயம்"),
        ("அபாயமே இல்லை", "குறைந்த அபாயம்"),
    ),
    "kannada": (
        ("ಗ್ಯಾರಂಟೀಡ್ ರಿಟರ್ನ್", "ಸಂಭಾವ್ಯ ಲಾಭ (ಮಾರುಕಟ್ಟೆ ಅಪಾಯಕ್ಕೆ ಒಳಪಟ್ಟಿದೆ)"),
        ("ಖಚಿತ ಲಾಭ", "ಸಂಭಾವ್ಯ ಲಾಭ (ಮಾರುಕಟ್ಟೆ ಅಪಾಯಕ್ಕೆ ಒಳಪಟ್ಟಿದೆ)"),
        ("ಜೀರೋ ರಿಸ್ಕ್", "ಕಡಿಮೆ ಅಪಾಯ"),
        ("ಯಾವುದೇ ಅಪಾಯವಿಲ್ಲ", "ಕಡಿಮೆ ಅಪಾಯ"),
    ),
    "bengali": (
        ("গ্যারান্টিড রিটার্ন", "সম্ভাব্য রিটার্ন (বাজার ঝুঁকি সাপেক্ষে)"),
        ("নিশ্চিত রিটার্ন", "সম্ভাব্য রিটার্ন (বাজার ঝুঁকি সাপেক্ষে)"),
        ("নিশ্চিত মুনাফা", "সম্ভাব্য মুনাফা (গ্যারান্টি নয়)"),
        ("জিরো রিস্ক", "কম ঝুঁকি"),
        ("কোনো ঝুঁকি নেই", "কম ঝুঁকি"),
    ),
    "marathi": (
        ("गॅरंटीड परतावा", "संभाव्य परतावा (बाजार जोखमीच्या अधीन)"),
        ("हमखास परतावा", "संभाव्य परतावा (बाजार जोखमीच्या अधीन)"),
        ("झिरो रिस्क", "कमी जोखीम"),
        ("कोणतीही जोखीम नाही", "कमी जोखीम"),
    ),
}


# ===========================================================================
# Normalised matching helpers + flattened lookup tables.
# ===========================================================================


def _normalize(text: str) -> str:
    """Casefold for case-insensitive matching (a no-op for caseless Indic scripts)."""
    return text.casefold()


_INVESTMENT_TERMS: frozenset[str] = frozenset(
    _normalize(term)
    for terms in INVESTMENT_TERMS_BY_LANGUAGE.values()
    for term in terms
)
_INSURANCE_TERMS: frozenset[str] = frozenset(
    _normalize(term)
    for terms in INSURANCE_TERMS_BY_LANGUAGE.values()
    for term in terms
)


def _mentions(text: str, terms: Iterable[str]) -> bool:
    haystack = _normalize(text)
    return any(term in haystack for term in terms)


def mentions_investment(text: str) -> bool:
    """True if ``text`` names an investment / market-linked product in any language."""
    return _mentions(text, _INVESTMENT_TERMS)


def mentions_insurance(text: str) -> bool:
    """True if ``text`` names an insurance product in any language."""
    return _mentions(text, _INSURANCE_TERMS)


def _build_blocked_claims() -> tuple[tuple[re.Pattern[str], str], ...]:
    """Compile English regex claims + escaped native literals into one table."""
    compiled: list[tuple[re.Pattern[str], str]] = [
        (re.compile(source, re.IGNORECASE), replacement)
        for source, replacement in _ENGLISH_BLOCKED_CLAIMS
    ]
    for claims in NATIVE_BLOCKED_CLAIMS_BY_LANGUAGE.values():
        compiled.extend(
            (re.compile(re.escape(phrase), re.IGNORECASE), replacement)
            for phrase, replacement in claims
        )
    return tuple(compiled)


# Disallowed marketing claims -> compliant rewrite, English + every language.
BLOCKED_CLAIMS: tuple[tuple[re.Pattern[str], str], ...] = _build_blocked_claims()
