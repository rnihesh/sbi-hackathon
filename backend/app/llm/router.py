"""Multi-provider LLM router: policy tiers, fallback chain, and cost ledger.

All LLM traffic in Sarathi flows through :class:`LLMRouter`. It selects a provider
chain per tier (``fast`` / ``smart``) based on which API keys are configured, falls
back to the next provider on error/timeout, records every attempt to the
``llm_calls`` table (fire-and-forget), and returns usage + cost in the response.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Sequence
from functools import lru_cache
from time import perf_counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.db import get_sessionmaker
from app.core.logging import get_logger
from app.llm.base import (
    ChatMessage,
    LLMError,
    LLMProvider,
    LLMResponse,
    StreamDone,
    StreamEvent,
    TextDelta,
    ToolSpec,
)
from app.llm.cost import compute_cost
from app.llm.providers.anthropic import AnthropicProvider
from app.llm.providers.gemini import GeminiProvider
from app.llm.providers.openai import OpenAIProvider
from app.models.enums import LlmTier

logger = get_logger(__name__)

# Preferred provider order; providers without credentials are skipped per tier.
PROVIDER_ORDER: tuple[str, ...] = ("openai", "gemini", "anthropic")


class LLMRouterError(LLMError):
    """Raised when every provider in a tier's chain fails."""


class LLMRouter:
    """Routes chat requests across providers with tier policy and fallback."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        providers: dict[str, LLMProvider] | None = None,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._sessionmaker = sessionmaker
        self._timeout = self._settings.llm_timeout_seconds
        self._default_max_tokens = self._settings.llm_default_max_tokens
        self._bg_tasks: set[asyncio.Task[None]] = set()

        self._providers: dict[str, LLMProvider] = providers or {
            "openai": OpenAIProvider(self._settings.openai_api_key),
            "gemini": GeminiProvider(self._settings.gemini_api_key),
            "anthropic": AnthropicProvider(self._settings.anthropic_api_key),
        }

        self._models: dict[str, dict[str, str]] = {
            "openai": {
                "fast": self._settings.openai_model_fast,
                "smart": self._settings.openai_model_smart,
            },
            "gemini": {
                "fast": self._settings.gemini_model_fast,
                "smart": self._settings.gemini_model_smart,
            },
            "anthropic": {
                "fast": self._settings.anthropic_model_fast,
                "smart": self._settings.anthropic_model_smart,
            },
        }

        self._chains: dict[str, list[tuple[str, str]]] = {
            tier: self._build_chain(tier) for tier in ("fast", "smart")
        }

        # Purpose -> preferred (provider, model_override) routing, config-driven.
        self._purpose_routing: dict[str, tuple[str, str | None]] = (
            self._settings.llm_purpose_routing_map
        )

    def _build_chain(self, tier: str) -> list[tuple[str, str]]:
        chain: list[tuple[str, str]] = []
        for name in PROVIDER_ORDER:
            provider = self._providers.get(name)
            if provider is None or not provider.has_credentials():
                continue
            model = self._models.get(name, {}).get(tier)
            if model:
                chain.append((name, model))
        return chain

    def available_providers(self, tier: str | LlmTier = "smart") -> list[str]:
        """Provider names (in order) that will be tried for ``tier``."""
        return [name for name, _ in self._chains.get(str(tier), [])]

    def _preferred_provider(self, purpose: str | None) -> tuple[str, str | None] | None:
        """Return the ``(provider, model_override)`` preferred for ``purpose``.

        A routing key matches when it equals any ':'-separated segment of the
        purpose (so ``"classify"`` matches ``"supervisor:classify"``). Returns
        ``None`` when no rule applies - the caller then uses plain chain order.
        """
        if not purpose or not self._purpose_routing:
            return None
        segments = purpose.split(":")
        for key, target in self._purpose_routing.items():
            if key == purpose or key in segments:
                return target
        return None

    def _chain_for(self, tier_str: str, purpose: str | None) -> list[tuple[str, str]]:
        """The tier chain, reordered so a purpose's preferred provider goes first.

        If the preferred provider has no credentials for this tier it is absent
        from the chain and the normal order stands (the fallback chain is
        untouched). An optional model override replaces that provider's model.
        """
        chain = list(self._chains.get(tier_str, []))
        preferred = self._preferred_provider(purpose)
        if preferred is None:
            return chain
        name, model_override = preferred
        idx = next((i for i, (candidate, _) in enumerate(chain) if candidate == name), None)
        if idx is None:
            return chain
        _, model = chain.pop(idx)
        chain.insert(0, (name, model_override or model))
        return chain

    async def chat(
        self,
        *,
        tier: str | LlmTier = "smart",
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec] | None = None,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        json_mode: bool = False,
        purpose: str | None = None,
    ) -> LLMResponse:
        """Run a chat completion for ``tier``, falling back across providers.

        Returns the first successful :class:`LLMResponse` (with ``cost_usd`` set).
        Raises :class:`LLMRouterError` if every configured provider fails.
        """
        tier_str = str(tier)
        chain = self._chain_for(tier_str, purpose)
        if not chain:
            raise LLMRouterError(
                f"no providers with credentials for tier {tier_str!r}; "
                "set OPENAI_API_KEY, GEMINI_API_KEY, or ANTHROPIC_API_KEY"
            )

        resolved_max_tokens = max_tokens or self._default_max_tokens
        errors: list[str] = []

        for name, model in chain:
            provider = self._providers[name]
            started = perf_counter()
            try:
                resp = await asyncio.wait_for(
                    provider.chat(
                        messages,
                        model=model,
                        tools=tools,
                        system=system,
                        temperature=temperature,
                        max_tokens=resolved_max_tokens,
                        json_mode=json_mode,
                        timeout=self._timeout,
                    ),
                    timeout=self._timeout + 5.0,
                )
            except (TimeoutError, Exception) as exc:
                latency_ms = int((perf_counter() - started) * 1000)
                errors.append(f"{name}: {exc}")
                logger.warning("llm_provider_failed", provider=name, model=model, error=str(exc))
                self._record(
                    provider=name,
                    model=model,
                    tier=tier_str,
                    tokens_in=0,
                    tokens_out=0,
                    latency_ms=latency_ms,
                    ok=False,
                    error=str(exc),
                    purpose=purpose,
                )
                continue

            latency_ms = int((perf_counter() - started) * 1000)
            resp.cost_usd = compute_cost(resp.model, resp.tokens_in, resp.tokens_out)
            self._record(
                provider=name,
                model=resp.model,
                tier=tier_str,
                tokens_in=resp.tokens_in,
                tokens_out=resp.tokens_out,
                latency_ms=latency_ms,
                ok=True,
                error=None,
                purpose=purpose,
            )
            return resp

        raise LLMRouterError(f"all providers failed for tier {tier_str!r}: {'; '.join(errors)}")

    async def stream_chat(
        self,
        *,
        tier: str | LlmTier = "smart",
        messages: Sequence[ChatMessage],
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        purpose: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a chat completion for ``tier`` with the same fallback + ledger
        guarantees as :meth:`chat`, for the final tool-free user-facing synthesis.

        Yields ``TextDelta``s as the provider produces them, then one
        ``StreamDone`` carrying the accumulated text + real usage/cost.

        Fallback semantics: if a provider fails *before* yielding any delta, fall
        through to the next provider in the chain (same as :meth:`chat`). Once a
        delta has been yielded the stream is committed to that provider - a
        mid-stream error propagates (switching would duplicate already-sent text).
        Every completed stream is recorded to the ``llm_calls`` ledger with real
        usage + cost.
        """
        tier_str = str(tier)
        chain = self._chain_for(tier_str, purpose)
        if not chain:
            raise LLMRouterError(
                f"no providers with credentials for tier {tier_str!r}; "
                "set OPENAI_API_KEY, GEMINI_API_KEY, or ANTHROPIC_API_KEY"
            )

        resolved_max_tokens = max_tokens or self._default_max_tokens
        errors: list[str] = []

        for name, model in chain:
            provider = self._providers[name]
            started = perf_counter()
            yielded_any = False
            final_response: LLMResponse | None = None
            try:
                async for event in provider.stream_chat(
                    messages,
                    model=model,
                    system=system,
                    temperature=temperature,
                    max_tokens=resolved_max_tokens,
                    timeout=self._timeout,
                ):
                    if isinstance(event, TextDelta):
                        yielded_any = True
                        yield event
                    else:  # StreamDone
                        final_response = event.response
            except (TimeoutError, Exception) as exc:
                latency_ms = int((perf_counter() - started) * 1000)
                errors.append(f"{name}: {exc}")
                logger.warning(
                    "llm_stream_provider_failed",
                    provider=name,
                    model=model,
                    error=str(exc),
                    after_deltas=yielded_any,
                )
                self._record(
                    provider=name,
                    model=model,
                    tier=tier_str,
                    tokens_in=0,
                    tokens_out=0,
                    latency_ms=latency_ms,
                    ok=False,
                    error=str(exc),
                    purpose=purpose,
                )
                if yielded_any:
                    # Deltas already sent: cannot switch providers without
                    # duplicating text - propagate so the caller can finalise.
                    raise
                continue

            latency_ms = int((perf_counter() - started) * 1000)
            if final_response is None:  # provider ended without a StreamDone
                final_response = LLMResponse(text="", model=model, provider=name)
            resolved_model = final_response.model or model
            final_response.cost_usd = compute_cost(
                resolved_model, final_response.tokens_in, final_response.tokens_out
            )
            self._record(
                provider=name,
                model=resolved_model,
                tier=tier_str,
                tokens_in=final_response.tokens_in,
                tokens_out=final_response.tokens_out,
                latency_ms=latency_ms,
                ok=True,
                error=None,
                purpose=purpose,
            )
            yield StreamDone(final_response)
            return

        raise LLMRouterError(
            f"all providers failed for tier {tier_str!r}: {'; '.join(errors)}"
        )

    # ------------------------------------------------------------------
    # cost ledger (fire-and-forget)
    # ------------------------------------------------------------------
    def _record(
        self,
        *,
        provider: str,
        model: str,
        tier: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
        ok: bool,
        error: str | None,
        purpose: str | None,
    ) -> None:
        if self._sessionmaker is None:
            return
        try:
            task = asyncio.create_task(
                self._persist_call(
                    provider=provider,
                    model=model,
                    tier=tier,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    latency_ms=latency_ms,
                    ok=ok,
                    error=error,
                    purpose=purpose,
                )
            )
        except RuntimeError:
            # No running event loop (e.g. sync context) - skip persistence.
            return
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _persist_call(self, **fields: Any) -> None:
        # Imported lazily to avoid import cost when persistence is disabled.
        from app.models.tracing import LlmCall

        assert self._sessionmaker is not None
        cost = compute_cost(fields["model"], fields["tokens_in"], fields["tokens_out"])
        try:
            async with self._sessionmaker() as session:
                session.add(
                    LlmCall(
                        provider=fields["provider"],
                        model=fields["model"],
                        tier=LlmTier(fields["tier"]),
                        tokens_in=fields["tokens_in"],
                        tokens_out=fields["tokens_out"],
                        cost_usd=cost,
                        latency_ms=fields["latency_ms"],
                        ok=fields["ok"],
                        error=fields["error"],
                        purpose=fields["purpose"],
                    )
                )
                await session.commit()
        except Exception as exc:
            logger.warning("llm_call_persist_failed", error=str(exc))


@lru_cache(maxsize=1)
def get_router() -> LLMRouter:
    """Return the process-wide cached router wired to settings + DB sessionmaker.

    Dev/test-only escape hatch: ``SARATHI_FAKE_LLM=1`` (never in prod) swaps in a
    network-free :class:`~app.llm.fake.FakeLLMRouter` so the agent pipeline can be
    exercised end-to-end before real provider keys exist.
    """
    settings = get_settings()
    if os.environ.get("SARATHI_FAKE_LLM") == "1" and settings.app_env.lower() != "prod":
        from app.llm.fake import FakeLLMRouter

        return FakeLLMRouter(settings)
    return LLMRouter(settings=settings, sessionmaker=get_sessionmaker())
