"""Dev/test-only deterministic router - never used in production.

Exists purely so a live pipeline check (seed → sim → event consumer → agent mesh)
can be exercised end-to-end before any real LLM key is configured. It makes zero
network calls and returns a fixed, compliant reply (empty JSON when
``json_mode=True`` so every JSON-parsing call site falls back to its documented
default/heuristic path; a short plain sentence otherwise).

Enabled ONLY via ``SARATHI_FAKE_LLM=1`` and only outside `APP_ENV=prod` - see
``app.llm.router.get_router``. Never enable this in a demo or production path.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from decimal import Decimal

from app.core.config import Settings
from app.llm.base import (
    ChatMessage,
    LLMResponse,
    StreamDone,
    StreamEvent,
    TextDelta,
    ToolSpec,
)
from app.llm.router import LLMRouter

_FAKE_TEXT = "Thanks for reaching out - I'm here to help with your banking today."


class FakeLLMRouter(LLMRouter):
    """Router double satisfying :class:`LLMRouter`'s public surface, no network I/O."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings=settings, providers={}, sessionmaker=None)

    async def chat(
        self,
        *,
        tier: str = "smart",
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec] | None = None,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        json_mode: bool = False,
        purpose: str | None = None,
    ) -> LLMResponse:
        text = "{}" if json_mode else _FAKE_TEXT
        return LLMResponse(
            text=text,
            tool_calls=[],
            tokens_in=8,
            tokens_out=len(text.split()),
            model="fake-dev",
            provider="fake",
            cost_usd=Decimal("0"),
        )

    async def stream_chat(
        self,
        *,
        tier: str = "smart",
        messages: Sequence[ChatMessage],
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        purpose: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        # Final synthesis is never json_mode, so always the plain compliant reply.
        words = _FAKE_TEXT.split(" ")
        for i, word in enumerate(words):
            yield TextDelta(word if i == len(words) - 1 else word + " ")
        yield StreamDone(
            LLMResponse(
                text=_FAKE_TEXT,
                tokens_in=8,
                tokens_out=len(words),
                model="fake-dev",
                provider="fake",
                cost_usd=Decimal("0"),
            )
        )
