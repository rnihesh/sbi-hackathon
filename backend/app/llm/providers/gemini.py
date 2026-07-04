"""Google Gemini provider adapter (google-genai async, native tool calling)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from google import genai
from google.genai import types

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

# Map common roles to Gemini content roles.
_ROLE_MAP = {"user": "user", "assistant": "model", "tool": "user"}


class GeminiProvider:
    """Adapter mapping the common LLM interface to the google-genai API."""

    provider = "gemini"

    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key
        self._client: genai.Client | None = None

    def has_credentials(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> genai.Client:
        if not self._api_key:
            raise LLMError("Gemini API key not configured")
        if self._client is None:
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    @staticmethod
    def _to_contents(messages: Sequence[ChatMessage]) -> list[types.Content]:
        contents: list[types.Content] = []
        for m in messages:
            if m.role == "system":
                continue  # carried via system_instruction
            role = _ROLE_MAP.get(m.role, "user")
            contents.append(types.Content(role=role, parts=[types.Part(text=m.content)]))
        return contents

    @staticmethod
    def _to_tools(tools: Sequence[ToolSpec]) -> list[types.Tool]:
        declarations = [
            types.FunctionDeclaration(
                name=t.name,
                description=t.description,
                parameters_json_schema=t.parameters,
            )
            for t in tools
        ]
        return [types.Tool(function_declarations=declarations)]

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

        config = types.GenerateContentConfig(
            system_instruction=system or None,
            temperature=temperature,
            max_output_tokens=max_tokens,
            tools=self._to_tools(tools) if tools else None,
            response_mime_type="application/json" if json_mode else None,
            http_options=types.HttpOptions(timeout=int(timeout * 1000)),
        )

        try:
            resp = await client.aio.models.generate_content(
                model=model,
                contents=self._to_contents(messages),
                config=config,
            )
        except Exception as exc:
            raise LLMError(f"gemini chat failed: {exc}") from exc

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        candidates = resp.candidates or []
        if candidates and candidates[0].content and candidates[0].content.parts:
            for part in candidates[0].content.parts:
                if part.text:
                    text_parts.append(part.text)
                if part.function_call and part.function_call.name:
                    args: dict[str, Any] = dict(part.function_call.args or {})
                    tool_calls.append(ToolCall(name=part.function_call.name, args=args))

        usage = resp.usage_metadata
        finish_reason = None
        if candidates and candidates[0].finish_reason is not None:
            finish_reason = str(candidates[0].finish_reason)

        return LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            tokens_in=usage.prompt_token_count or 0 if usage else 0,
            tokens_out=usage.candidates_token_count or 0 if usage else 0,
            model=model,
            provider=self.provider,
            finish_reason=finish_reason,
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
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            temperature=temperature,
            max_output_tokens=max_tokens,
            http_options=types.HttpOptions(timeout=int(timeout * 1000)),
        )

        text_parts: list[str] = []
        tokens_in = 0
        tokens_out = 0
        finish_reason: str | None = None
        try:
            stream = await client.aio.models.generate_content_stream(
                model=model,
                contents=self._to_contents(messages),
                config=config,
            )
            async for chunk in stream:
                candidates = chunk.candidates or []
                if candidates and candidates[0].content and candidates[0].content.parts:
                    for part in candidates[0].content.parts:
                        if part.text:
                            text_parts.append(part.text)
                            yield TextDelta(part.text)
                if candidates and candidates[0].finish_reason is not None:
                    finish_reason = str(candidates[0].finish_reason)
                # Usage accumulates across chunks; the last non-null wins the total.
                usage = chunk.usage_metadata
                if usage is not None:
                    tokens_in = usage.prompt_token_count or tokens_in
                    tokens_out = usage.candidates_token_count or tokens_out
        except Exception as exc:
            raise LLMError(f"gemini stream failed: {exc}") from exc

        yield StreamDone(
            LLMResponse(
                text="".join(text_parts),
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                model=model,
                provider=self.provider,
                finish_reason=finish_reason,
            )
        )
