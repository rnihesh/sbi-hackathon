"""Provider-agnostic LLM primitives shared by the router and every provider."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Protocol, runtime_checkable

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(slots=True)
class ChatMessage:
    """A single conversational message.

    ``system`` messages may appear in the list, but providers generally prefer the
    dedicated ``system`` argument to :meth:`LLMProvider.chat`.
    """

    role: Role
    content: str


@dataclass(slots=True)
class ToolSpec:
    """A callable tool exposed to the model (name + JSON-schema parameters)."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(slots=True)
class ToolCall:
    """A tool invocation requested by the model."""

    name: str
    args: dict[str, Any]


@dataclass(slots=True)
class LLMResponse:
    """Normalised result of a single provider call."""

    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""
    provider: str = ""
    finish_reason: str | None = None
    cost_usd: Decimal = Decimal("0")


class LLMError(Exception):
    """Base class for LLM provider/router failures."""


@runtime_checkable
class LLMProvider(Protocol):
    """Common async interface every provider adapter implements.

    ``model`` is passed per-call so a single provider instance can serve both the
    ``fast`` and ``smart`` tiers.
    """

    provider: str

    def has_credentials(self) -> bool:
        """Whether this provider has an API key configured."""
        ...

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
        """Send a chat completion request and return a normalised response."""
        ...
