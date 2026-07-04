"""Anthropic provider adapter (AsyncAnthropic, native tool calling)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from anthropic import AsyncAnthropic

from app.llm.base import ChatMessage, LLMError, LLMResponse, ToolCall, ToolSpec

_JSON_SUFFIX = "\n\nRespond ONLY with a single valid JSON object and no other text."


class AnthropicProvider:
    """Adapter mapping the common LLM interface to the Anthropic Messages API."""

    provider = "anthropic"

    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key
        self._client: AsyncAnthropic | None = None

    def has_credentials(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> AsyncAnthropic:
        if not self._api_key:
            raise LLMError("Anthropic API key not configured")
        if self._client is None:
            self._client = AsyncAnthropic(api_key=self._api_key)
        return self._client

    @staticmethod
    def _to_messages(messages: Sequence[ChatMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                continue  # carried via the system argument
            role = "assistant" if m.role == "assistant" else "user"
            out.append({"role": role, "content": m.content})
        return out

    @staticmethod
    def _to_tools(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in tools
        ]

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
        client = self._get_client()

        effective_system = system or ""
        if json_mode:
            effective_system = (effective_system + _JSON_SUFFIX).strip()

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": self._to_messages(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "timeout": timeout,
        }
        if effective_system:
            kwargs["system"] = effective_system
        if tools:
            kwargs["tools"] = self._to_tools(tools)

        try:
            resp = await client.messages.create(**kwargs)
        except Exception as exc:
            raise LLMError(f"anthropic chat failed: {exc}") from exc

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                args = block.input if isinstance(block.input, dict) else {}
                tool_calls.append(ToolCall(name=block.name, args=args))

        return LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            tokens_in=resp.usage.input_tokens,
            tokens_out=resp.usage.output_tokens,
            model=resp.model or model,
            provider=self.provider,
            finish_reason=resp.stop_reason,
        )
