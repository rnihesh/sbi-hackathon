"""Tests for the multi-provider LLM router (fake providers, no network)."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

import pytest

from app.core.config import Settings
from app.llm.base import ChatMessage, LLMError, LLMResponse, ToolCall, ToolSpec
from app.llm.cost import compute_cost
from app.llm.router import LLMRouter, LLMRouterError


class FakeProvider:
    """In-memory provider double implementing the LLMProvider protocol."""

    def __init__(
        self,
        provider: str,
        *,
        credentials: bool = True,
        fail: bool = False,
        response: LLMResponse | None = None,
    ) -> None:
        self.provider = provider
        self._credentials = credentials
        self._fail = fail
        self._response = response
        self.calls: list[dict[str, object]] = []

    def has_credentials(self) -> bool:
        return self._credentials

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        tools: Sequence[ToolSpec] | None = None,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        json_mode: bool = False,
        timeout: float = 60.0,
    ) -> LLMResponse:
        self.calls.append({"model": model, "tools": tools, "system": system})
        if self._fail:
            raise LLMError(f"{self.provider} boom")
        if self._response is not None:
            return self._response
        return LLMResponse(
            text=f"{self.provider}:{model}",
            tokens_in=10,
            tokens_out=20,
            model=model,
            provider=self.provider,
        )


def _settings() -> Settings:
    # Keys are irrelevant when providers are injected; models come from settings.
    return Settings(openai_api_key=None, gemini_api_key=None, anthropic_api_key=None)


MESSAGES = [ChatMessage(role="user", content="hi")]


async def test_fallback_chain_uses_next_provider_on_failure() -> None:
    openai = FakeProvider("openai", fail=True)
    gemini = FakeProvider("gemini")
    anthropic = FakeProvider("anthropic")
    router = LLMRouter(
        settings=_settings(),
        providers={"openai": openai, "gemini": gemini, "anthropic": anthropic},
    )

    resp = await router.chat(tier="smart", messages=MESSAGES)

    assert resp.provider == "gemini"
    assert len(openai.calls) == 1  # tried and failed
    assert len(gemini.calls) == 1  # fell back and succeeded
    assert len(anthropic.calls) == 0  # never reached


async def test_all_providers_fail_raises() -> None:
    router = LLMRouter(
        settings=_settings(),
        providers={
            "openai": FakeProvider("openai", fail=True),
            "gemini": FakeProvider("gemini", fail=True),
            "anthropic": FakeProvider("anthropic", fail=True),
        },
    )
    with pytest.raises(LLMRouterError):
        await router.chat(tier="fast", messages=MESSAGES)


async def test_provider_order_skips_missing_credentials() -> None:
    router = LLMRouter(
        settings=_settings(),
        providers={
            "openai": FakeProvider("openai", credentials=False),
            "gemini": FakeProvider("gemini", credentials=True),
            "anthropic": FakeProvider("anthropic", credentials=False),
        },
    )
    assert router.available_providers("smart") == ["gemini"]
    resp = await router.chat(tier="smart", messages=MESSAGES)
    assert resp.provider == "gemini"


def test_tier_selection_respects_available_keys() -> None:
    # Real providers; only the gemini key is present.
    settings = Settings(openai_api_key=None, gemini_api_key="k", anthropic_api_key=None)
    router = LLMRouter(settings=settings)
    assert router.available_providers("fast") == ["gemini"]
    assert router.available_providers("smart") == ["gemini"]


# ===========================================================================
# Runtime OpenAI model override (a console-set runtime setting resolved per call)
# ===========================================================================


async def test_openai_model_override_swaps_only_openai_model() -> None:
    openai = FakeProvider("openai")
    gemini = FakeProvider("gemini")

    async def override(_tier: str) -> str | None:
        return "gpt-4o"

    router = LLMRouter(
        settings=_settings(),
        providers={"openai": openai, "gemini": gemini},
        openai_model_override=override,
    )

    resp = await router.chat(tier="smart", messages=MESSAGES)
    assert resp.provider == "openai"
    assert resp.model == "gpt-4o"  # the static "gpt-4.1" was overridden
    assert openai.calls[0]["model"] == "gpt-4o"


async def test_openai_model_override_noop_when_unset_uses_static_model() -> None:
    openai = FakeProvider("openai")
    settings = _settings()

    async def override(_tier: str) -> str | None:
        return None

    router = LLMRouter(
        settings=settings,
        providers={"openai": openai},
        openai_model_override=override,
    )

    resp = await router.chat(tier="fast", messages=MESSAGES)
    # No override set -> the statically-configured fast model is used unchanged.
    assert resp.model == settings.openai_model_fast


def test_no_keys_means_empty_chain() -> None:
    router = LLMRouter(settings=_settings())
    assert router.available_providers("smart") == []


async def test_no_providers_raises() -> None:
    router = LLMRouter(settings=_settings())
    with pytest.raises(LLMRouterError):
        await router.chat(tier="smart", messages=MESSAGES)


async def test_tool_calls_round_trip_through_router() -> None:
    tool = ToolSpec(
        name="get_balance",
        description="Fetch account balance",
        parameters={"type": "object", "properties": {"account_id": {"type": "string"}}},
    )
    canned = LLMResponse(
        text="",
        tool_calls=[ToolCall(name="get_balance", args={"account_id": "acc_1"})],
        tokens_in=5,
        tokens_out=7,
        model="gpt-4.1",
        provider="openai",
    )
    provider = FakeProvider("openai", response=canned)
    router = LLMRouter(settings=_settings(), providers={"openai": provider})

    resp = await router.chat(tier="smart", messages=MESSAGES, tools=[tool])

    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "get_balance"
    assert resp.tool_calls[0].args == {"account_id": "acc_1"}
    # tools were forwarded to the provider unchanged
    assert provider.calls[0]["tools"] == [tool]


async def test_cost_is_computed_and_attached() -> None:
    canned = LLMResponse(
        text="ok",
        tokens_in=1000,
        tokens_out=2000,
        model="gpt-4o-mini",
        provider="openai",
    )
    router = LLMRouter(
        settings=_settings(),
        providers={"openai": FakeProvider("openai", response=canned)},
    )
    resp = await router.chat(tier="smart", messages=MESSAGES)
    assert resp.cost_usd == compute_cost("gpt-4o-mini", 1000, 2000)
    assert resp.cost_usd > Decimal("0")


async def test_smart_tier_prefers_openai_when_all_available() -> None:
    router = LLMRouter(
        settings=_settings(),
        providers={
            "openai": FakeProvider("openai"),
            "gemini": FakeProvider("gemini"),
            "anthropic": FakeProvider("anthropic"),
        },
    )
    resp = await router.chat(tier="smart", messages=MESSAGES)
    assert resp.provider == "openai"  # first in PROVIDER_ORDER


# ---------------------------------------------------------------------------
# Purpose-based provider routing
# ---------------------------------------------------------------------------


def test_purpose_routing_map_parses_provider_and_optional_model() -> None:
    mapping = _settings().llm_purpose_routing_map
    assert mapping["classify"] == ("gemini", "gemini-2.5-flash-lite")
    assert mapping["embedding"] == ("openai", None)


async def test_purpose_routing_prefers_mapped_provider_and_model_override() -> None:
    openai = FakeProvider("openai")
    gemini = FakeProvider("gemini")
    router = LLMRouter(
        settings=_settings(), providers={"openai": openai, "gemini": gemini}
    )

    # "classify" segment of the purpose maps to gemini + a model override, even
    # though openai is first in PROVIDER_ORDER.
    resp = await router.chat(tier="fast", messages=MESSAGES, purpose="supervisor:classify")

    assert resp.provider == "gemini"
    assert len(gemini.calls) == 1
    assert gemini.calls[0]["model"] == "gemini-2.5-flash-lite"  # override applied
    assert len(openai.calls) == 0  # preferred provider reached first


async def test_purpose_routing_falls_back_when_preferred_fails() -> None:
    gemini = FakeProvider("gemini", fail=True)
    openai = FakeProvider("openai")
    router = LLMRouter(
        settings=_settings(), providers={"openai": openai, "gemini": gemini}
    )

    resp = await router.chat(tier="fast", messages=MESSAGES, purpose="supervisor:classify")

    # Preferred gemini failed -> the normal fallback chain still applies.
    assert resp.provider == "openai"
    assert len(gemini.calls) == 1
    assert len(openai.calls) == 1


async def test_purpose_routing_unknown_purpose_uses_chain_order() -> None:
    openai = FakeProvider("openai")
    gemini = FakeProvider("gemini")
    router = LLMRouter(
        settings=_settings(), providers={"openai": openai, "gemini": gemini}
    )

    resp = await router.chat(tier="smart", messages=MESSAGES, purpose="engagement:score_churn")

    assert resp.provider == "openai"  # no rule -> PROVIDER_ORDER
    assert len(gemini.calls) == 0


async def test_purpose_routing_skips_preferred_without_credentials() -> None:
    openai = FakeProvider("openai")
    gemini = FakeProvider("gemini", credentials=False)
    router = LLMRouter(
        settings=_settings(), providers={"openai": openai, "gemini": gemini}
    )

    resp = await router.chat(tier="fast", messages=MESSAGES, purpose="supervisor:classify")

    # Gemini is preferred but has no key -> normal chain, openai answers.
    assert resp.provider == "openai"
    assert len(gemini.calls) == 0
    assert len(openai.calls) == 1
