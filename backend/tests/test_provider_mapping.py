"""Tests for provider request-mapping helpers (no network calls)."""

from __future__ import annotations

from app.llm.base import ChatMessage, ToolSpec
from app.llm.providers.anthropic import AnthropicProvider
from app.llm.providers.gemini import GeminiProvider
from app.llm.providers.openai import OpenAIProvider

TOOL = ToolSpec(
    name="get_balance",
    description="Fetch account balance",
    parameters={"type": "object", "properties": {"account_id": {"type": "string"}}},
)
CONVO = [
    ChatMessage(role="system", content="be helpful"),
    ChatMessage(role="user", content="hello"),
    ChatMessage(role="assistant", content="hi there"),
]


def test_openai_message_mapping_prepends_system() -> None:
    out = OpenAIProvider._to_openai_messages(CONVO, system="ROOT")
    assert out[0] == {"role": "system", "content": "ROOT"}
    # the ChatMessage system entry is kept as-is after the injected system
    assert {"role": "user", "content": "hello"} in out
    assert {"role": "assistant", "content": "hi there"} in out


def test_openai_tool_mapping() -> None:
    out = OpenAIProvider._to_openai_tools([TOOL])
    assert out[0]["type"] == "function"
    fn = out[0]["function"]
    assert fn["name"] == "get_balance"
    assert fn["parameters"] == TOOL.parameters


def test_anthropic_tool_mapping_uses_input_schema() -> None:
    out = AnthropicProvider._to_tools([TOOL])
    assert out[0]["name"] == "get_balance"
    assert out[0]["input_schema"] == TOOL.parameters
    assert "parameters" not in out[0]


def test_anthropic_message_mapping_drops_system_role() -> None:
    out = AnthropicProvider._to_messages(CONVO)
    roles = [m["role"] for m in out]
    assert "system" not in roles
    assert roles == ["user", "assistant"]


def test_gemini_content_mapping_maps_assistant_to_model() -> None:
    out = GeminiProvider._to_contents(CONVO)
    roles = [c.role for c in out]
    assert roles == ["user", "model"]  # system skipped, assistant -> model


def test_gemini_tool_mapping_wraps_function_declarations() -> None:
    out = GeminiProvider._to_tools([TOOL])
    assert len(out) == 1
    decls = out[0].function_declarations
    assert decls is not None
    assert decls[0].name == "get_balance"
