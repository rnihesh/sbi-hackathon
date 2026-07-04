"""Vernacular chat: supported languages + the shared system-prompt directive.

Sarathi's underlying models (gpt-4o-mini, gemini-2.5-flash) handle Hindi,
Hinglish, and the other listed Indian languages natively - there is no
translation layer. This module owns two things: the free-string vocabulary of
supported ``preferred_language`` values (kept as plain strings, not a DB enum,
so adding a language is a one-line change with no migration) and
``language_directive``, the prompt-text builder every user-facing system
prompt (supervisor smalltalk + the three specialists) appends.

Pure string building, no I/O, no LLM calls - safe and cheap to unit test.
"""

from __future__ import annotations

SUPPORTED_LANGUAGES: tuple[str, ...] = (
    "english",
    "hindi",
    "hinglish",
    "telugu",
    "tamil",
    "kannada",
    "bengali",
    "marathi",
)

_LANGUAGE_LABELS: dict[str, str] = {
    "english": "English",
    "hindi": "Hindi",
    "hinglish": "Hinglish",
    "telugu": "Telugu",
    "tamil": "Tamil",
    "kannada": "Kannada",
    "bengali": "Bengali",
    "marathi": "Marathi",
}

_AUTO_DIRECTIVE = (
    "Respond in the language the user writes in. If they write in Hindi, "
    "Hinglish, Telugu, Tamil or another Indian language, reply in that "
    "language naturally. Default to English."
)

# Mandated disclosures are appended verbatim by the policy engine after the
# model's draft - they must stay in English regardless of the chosen reply
# language, so every directive ends with this rule.
_DISCLOSURE_RULE = (
    "Disclosures mandated by policy stay in English - compliance text must "
    "never be paraphrased or translated."
)


def language_directive(preferred: str | None) -> str:
    """Build the language-behaviour block for a user-facing system prompt.

    - ``preferred`` a supported, non-English language: instruct the model to
      reply in it, keeping banking terms/numbers clear and phrasing warm and
      simple, while still following the user if they switch languages.
    - ``preferred`` is ``None``, empty, "english", or not a recognised value:
      auto-detect - reply in whatever language the user writes in, defaulting
      to English.

    Either branch always ends with the mandated-disclosures-stay-English rule.
    """
    normalized = (preferred or "").strip().lower()
    if normalized and normalized != "english" and normalized in SUPPORTED_LANGUAGES:
        label = _LANGUAGE_LABELS[normalized]
        directive = (
            f"Respond in {label}. Keep banking/product terms and numbers clear; "
            "use simple, warm phrasing. If the user writes in a different "
            "language, follow the user."
        )
    else:
        directive = _AUTO_DIRECTIVE
    return f"{directive} {_DISCLOSURE_RULE}"
