"""Multi-provider LLM router: policy tiers, fallback chain, and cost ledger.

All LLM traffic in Sarathi flows through :class:`LLMRouter`. It selects a provider
chain per tier (``fast`` / ``smart``) based on which API keys are configured, falls
back to the next provider on error/timeout, records every attempt to the
``llm_calls`` table (fire-and-forget), and returns usage + cost in the response.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from functools import lru_cache
from time import perf_counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.db import get_sessionmaker
from app.core.logging import get_logger
from app.llm.base import ChatMessage, LLMError, LLMProvider, LLMResponse, ToolSpec
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
        chain = self._chains.get(tier_str, [])
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
