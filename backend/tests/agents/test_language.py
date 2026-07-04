"""Vernacular chat: language directive builder + its wiring into every \
user-facing system prompt (supervisor smalltalk + the three specialists).

Pure prompt-text assertions - no LLM calls, per the hard budget rule.
"""

from __future__ import annotations

from typing import Any

from app.agents import acquisition, adoption, engagement
from app.agents.language import SUPPORTED_LANGUAGES, language_directive
from app.agents.state import new_state
from app.agents.supervisor import smalltalk_node
from app.models.customer import Customer
from tests.agents.conftest import FakeRouter, ScriptedHandler

# ---------------------------------------------------------------------------
# language_directive
# ---------------------------------------------------------------------------


def test_directive_none_is_auto_detect() -> None:
    directive = language_directive(None)
    assert "language the user writes in" in directive
    assert "Default to English" in directive


def test_directive_english_is_auto_detect() -> None:
    # Explicit "english" behaves the same as unset - auto-detect, not a pin.
    assert language_directive("english") == language_directive(None)


def test_directive_hindi_pins_the_reply_language() -> None:
    directive = language_directive("hindi")
    assert "Respond in Hindi." in directive
    assert "simple, warm phrasing" in directive


def test_directive_is_case_and_whitespace_insensitive() -> None:
    assert language_directive("  HINDI  ") == language_directive("hindi")


def test_directive_unknown_value_falls_back_to_auto() -> None:
    assert language_directive("klingon") == language_directive(None)


def test_directive_always_protects_mandated_disclosures() -> None:
    for preferred in (None, "english", *SUPPORTED_LANGUAGES):
        assert "stay in English" in language_directive(preferred)


def test_directive_covers_every_supported_non_english_language() -> None:
    for lang in SUPPORTED_LANGUAGES:
        if lang == "english":
            continue
        directive = language_directive(lang)
        assert directive != language_directive(None)
        assert "Respond in" in directive


def test_no_em_dash_in_any_directive() -> None:
    # `make check-emdash` bans the raw glyph repo-wide, so it can't appear
    # literally in this file - build it from its code point instead.
    em_dash = chr(0x2014)
    for preferred in (None, "english", *SUPPORTED_LANGUAGES, "klingon"):
        assert em_dash not in language_directive(preferred)


# ---------------------------------------------------------------------------
# Specialist _system builders wire the directive in via profile["preferred_language"]
# ---------------------------------------------------------------------------

_SPECIALISTS: list[Any] = [acquisition, adoption, engagement]


def _state() -> Any:
    return new_state(conversation_id="c-lang", customer_id=None, user_text="hello")


def test_every_specialist_system_includes_auto_directive_by_default() -> None:
    state = _state()
    for module in _SPECIALISTS:
        system = module._system(None, state, {}, [])  # type: ignore[arg-type]
        assert language_directive(None) in system, module.__name__


def test_every_specialist_system_includes_pinned_directive() -> None:
    state = _state()
    profile = {"preferred_language": "tamil"}
    for module in _SPECIALISTS:
        system = module._system(None, state, profile, [])  # type: ignore[arg-type]
        assert language_directive("tamil") in system, module.__name__
        assert "Respond in Tamil." in system


def test_specialist_system_ignores_unsupported_preference() -> None:
    state = _state()
    profile = {"preferred_language": "klingon"}
    for module in _SPECIALISTS:
        system = module._system(None, state, profile, [])  # type: ignore[arg-type]
        assert language_directive(None) in system, module.__name__


# ---------------------------------------------------------------------------
# Supervisor smalltalk: fetches the customer's preference and builds the
# directive into the system prompt sent to the router (FakeRouter, no live call).
# ---------------------------------------------------------------------------


async def test_smalltalk_system_prompt_uses_customer_preferred_language(  # type: ignore[no-untyped-def]
    make_ctx, db
) -> None:
    customer = Customer(full_name="Priya", preferred_language="telugu")
    db.add(customer)
    await db.flush()

    router = FakeRouter(ScriptedHandler(default_text="Namaste!"))
    ctx = await make_ctx(router, customer_id=customer.id)
    state = new_state(conversation_id="c-smalltalk", customer_id=str(customer.id), user_text="hi")

    await smalltalk_node(state, {"configurable": {"ctx": ctx}})

    system = router.calls[-1]["system"] or ""
    assert "Respond in Telugu." in system


async def test_smalltalk_system_prompt_defaults_to_auto_without_customer(  # type: ignore[no-untyped-def]
    make_ctx,
) -> None:
    router = FakeRouter(ScriptedHandler(default_text="Hello!"))
    ctx = await make_ctx(router)
    state = new_state(conversation_id="c-smalltalk-anon", customer_id=None, user_text="hi")

    await smalltalk_node(state, {"configurable": {"ctx": ctx}})

    system = router.calls[-1]["system"] or ""
    assert language_directive(None) in system
