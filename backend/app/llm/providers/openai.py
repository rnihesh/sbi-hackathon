"""OpenAI provider adapter (AsyncOpenAI, native tool calling)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

from openai import AsyncOpenAI

from app.llm.base import (
    ChatMessage,
    LLMError,
    LLMResponse,
    StreamDone,
    StreamEvent,
    TextDelta,
    ToolCall,
    ToolSpec,
)


class OpenAIProvider:
    """Adapter mapping the common LLM interface to the OpenAI Chat Completions API."""

    provider = "openai"

    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key
        self._client: AsyncOpenAI | None = None

    def has_credentials(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> AsyncOpenAI:
        if not self._api_key:
            raise LLMError("OpenAI API key not configured")
        if self._client is None:
            self._client = AsyncOpenAI(api_key=self._api_key)
        return self._client

    @staticmethod
    def _to_openai_messages(
        messages: Sequence[ChatMessage], system: str | None
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if system:
            out.append({"role": "system", "content": system})
        for m in messages:
            out.append({"role": m.role, "content": m.content})
        return out

    @staticmethod
    def _to_openai_tools(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
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
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": self._to_openai_messages(messages, system),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": timeout,
        }
        if tools:
            kwargs["tools"] = self._to_openai_tools(tools)
            kwargs["tool_choice"] = "auto"
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            resp = await client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise LLMError(f"openai chat failed: {exc}") from exc

        choice = resp.choices[0]
        message = choice.message
        tool_calls: list[ToolCall] = []
        for tc in message.tool_calls or []:
            if tc.type != "function":
                continue
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}
            tool_calls.append(ToolCall(name=tc.function.name, args=args))

        usage = resp.usage
        return LLMResponse(
            text=message.content or "",
            tool_calls=tool_calls,
            tokens_in=usage.prompt_tokens if usage else 0,
            tokens_out=usage.completion_tokens if usage else 0,
            model=resp.model or model,
            provider=self.provider,
            finish_reason=choice.finish_reason,
        )

    async def stream_chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        timeout: float = 60.0,
    ) -> AsyncIterator[StreamEvent]:
        client = self._get_client()
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": self._to_openai_messages(messages, system),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": timeout,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        text_parts: list[str] = []
        tokens_in = 0
        tokens_out = 0
        resolved_model = model
        finish_reason: str | None = None
        try:
            stream = await client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if chunk.model:
                    resolved_model = chunk.model
                for choice in chunk.choices:
                    delta = choice.delta
                    if delta is not None and delta.content:
                        text_parts.append(delta.content)
                        yield TextDelta(delta.content)
                    if choice.finish_reason:
                        finish_reason = choice.finish_reason
                # The usage-bearing final chunk (include_usage) has empty choices.
                if chunk.usage is not None:
                    tokens_in = chunk.usage.prompt_tokens
                    tokens_out = chunk.usage.completion_tokens
        except Exception as exc:
            raise LLMError(f"openai stream failed: {exc}") from exc

        yield StreamDone(
            LLMResponse(
                text="".join(text_parts),
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                model=resolved_model or model,
                provider=self.provider,
                finish_reason=finish_reason,
            )
        )
