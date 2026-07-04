"""Tool abstraction and the specialist tool-loop runner.

A specialist is a system prompt + a toolset. :func:`run_agent_loop` drives the
ReAct-style loop: call the LLM (with tools) → if it emits tool calls, execute
them (restoring redacted PII into the real args), feed redacted observations
back, repeat up to ``max_iters`` → otherwise return the model's text as the
draft answer. Every LLM and tool step is traced and streamed.

Tool results are fed back as ``user`` observation messages rather than the
provider-native ``tool`` role: the shared router uses a minimal message model
(role+content only, no tool_call_id), so the ReAct text protocol is the portable
choice across OpenAI/Gemini/Anthropic.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import orjson

from app.agents.context import AgentContext
from app.agents.state import AgentState, ChatTurn
from app.llm.base import ChatMessage, ToolSpec
from app.models.enums import AgentStepKind

ToolArgs = dict[str, Any]
ToolResult = dict[str, Any]
ToolImpl = Callable[[AgentContext, AgentState, ToolArgs], Awaitable[ToolResult]]


@dataclass(slots=True)
class Tool:
    spec: ToolSpec
    impl: ToolImpl

    @property
    def name(self) -> str:
        return self.spec.name


def make_tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    impl: ToolImpl,
) -> Tool:
    """Build a :class:`Tool` from a name, description, JSON-schema params, impl."""
    return Tool(spec=ToolSpec(name=name, description=description, parameters=parameters), impl=impl)


def obj_schema(
    properties: dict[str, dict[str, Any]], required: list[str] | None = None
) -> dict[str, Any]:
    """Shorthand for a JSON-Schema object with ``properties``/``required``."""
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def _dumps(value: Any) -> str:
    return orjson.dumps(value, default=str).decode("utf-8")


def _truncate(value: Any, limit: int = 2000) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "…"
    return value


async def run_agent_loop(
    ctx: AgentContext,
    state: AgentState,
    *,
    agent_name: str,
    node_name: str,
    system: str,
    tools: dict[str, Tool],
    history: list[ChatTurn],
    tier: str = "smart",
    max_iters: int = 6,
) -> str:
    """Run a bounded tool loop for a specialist and return its draft answer."""
    messages: list[ChatMessage] = [
        ChatMessage(role=t["role"], content=t["content"]) for t in history  # type: ignore[arg-type]
    ]
    tool_specs = [t.spec for t in tools.values()]
    draft = ""

    for iteration in range(max_iters):
        started = perf_counter()
        resp = await ctx.router.chat(
            tier=tier,
            messages=messages,
            tools=tool_specs or None,
            system=system,
            purpose=f"{agent_name}:loop",
        )
        latency_ms = int((perf_counter() - started) * 1000)
        await ctx.tracer.step(
            node=node_name,
            kind=AgentStepKind.LLM,
            name=f"{agent_name}.reason",
            input={"iteration": iteration, "messages": len(messages)},
            output={
                "text": _truncate(resp.text),
                "tool_calls": [tc.name for tc in resp.tool_calls],
            },
            model=resp.model,
            tokens_in=resp.tokens_in,
            tokens_out=resp.tokens_out,
            cost_usd=resp.cost_usd,
            latency_ms=latency_ms,
        )

        if not resp.tool_calls:
            draft = resp.text
            break

        if resp.text:
            messages.append(ChatMessage(role="assistant", content=resp.text))

        for call in resp.tool_calls:
            redacted_args = call.args  # placeholders only — what the LLM actually saw
            await ctx.emit(
                {
                    "type": "tool_start",
                    "node": node_name,
                    "tool": call.name,
                    "args": redacted_args,
                }
            )
            t0 = perf_counter()
            tool = tools.get(call.name)
            if tool is None:
                result: dict[str, Any] = {"error": f"unknown tool '{call.name}'"}
            else:
                real_args = ctx.restore_args(call.args)
                try:
                    result = await tool.impl(ctx, state, real_args)
                except Exception as exc:
                    result = {"error": f"{type(exc).__name__}: {exc}"}
            tool_latency = int((perf_counter() - t0) * 1000)

            await ctx.tracer.step(
                node=node_name,
                kind=AgentStepKind.TOOL,
                name=call.name,
                input=redacted_args,  # redacted input (PII placeholders)
                output=result,
                latency_ms=tool_latency,
            )
            await ctx.emit(
                {"type": "tool_end", "node": node_name, "tool": call.name, "result": result}
            )

            # Redact any PII in the tool output before it re-enters the LLM context.
            observation = ctx.redactor.redact_text(_dumps(result))
            messages.append(
                ChatMessage(role="user", content=f"OBSERVATION[{call.name}]: {observation}")
            )

    if not draft:
        # Loop exhausted its tool budget — force a final, tool-free synthesis.
        started = perf_counter()
        resp = await ctx.router.chat(
            tier=tier,
            messages=[
                *messages,
                ChatMessage(
                    role="user",
                    content="Summarise the outcome for the customer now, in plain language.",
                ),
            ],
            system=system,
            purpose=f"{agent_name}:final",
        )
        await ctx.tracer.step(
            node=node_name,
            kind=AgentStepKind.LLM,
            name=f"{agent_name}.finalize",
            input={"forced": True},
            output={"text": _truncate(resp.text)},
            model=resp.model,
            tokens_in=resp.tokens_in,
            tokens_out=resp.tokens_out,
            cost_usd=resp.cost_usd,
            latency_ms=int((perf_counter() - started) * 1000),
        )
        draft = resp.text or "I've noted your request and a relationship manager will follow up."

    return draft
