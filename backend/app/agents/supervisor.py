"""Supervisor: intent classification, routing, and final synthesis.

All turns enter and leave through the supervisor. It classifies intent (fast
tier, JSON mode, India-banking few-shot), routes to a specialist (or answers
small talk directly), and - after the specialist runs - performs the single
compliant synthesis: policy check, mandated-disclosure append, audit, and
episodic-memory write.
"""

from __future__ import annotations

import uuid
from time import perf_counter
from typing import Any

import orjson
from langchain_core.runnables import RunnableConfig

from app.agents import memory
from app.agents.context import AgentContext
from app.agents.language import language_directive
from app.agents.state import AgentState, ChatTurn
from app.agents.toolkit import Tool, run_agent_loop, stream_final_answer
from app.llm.base import ChatMessage
from app.models.customer import Customer
from app.models.enums import AgentStepKind, MemoryKind

VALID_INTENTS = ("acquisition", "adoption", "engagement", "smalltalk")

_CLASSIFIER_SYSTEM = """You are the routing brain of Sarathi, an agentic relationship \
manager for an Indian retail bank (SBI-style). Classify the user's latest message into \
exactly one intent:

- "acquisition": prospect/onboarding - opening a new account, KYC, becoming a customer, \
product discovery for someone not yet onboarded.
- "adoption": an existing customer using/activating features - UPI, autopay, cards, \
netbanking, dormant products, "how do I…", balance/usage questions, walkthroughs.
- "engagement": life events and next-best-action - bonus/raise, new job, new child, home \
buying, retirement, planning, churn/leaving concerns.
- "smalltalk": greetings, thanks, or general questions needing no account action.

Examples:
- "I want to open a savings account" -> acquisition
- "Help me start using UPI on my account" -> adoption
- "I just got a big bonus, what should I do with it?" -> engagement
- "What's my current balance?" -> adoption
- "Hi, who are you?" -> smalltalk
- "I'm thinking of switching banks" -> engagement
- "I got married last month" -> engagement
- "How do I set up an FD?" -> adoption

Respond with ONLY JSON: {"intent": "<one of acquisition|adoption|engagement|smalltalk>", \
"reason": "<short>"}."""


def get_ctx(config: RunnableConfig) -> AgentContext:
    """Extract the per-run :class:`AgentContext` from the graph config."""
    configurable = config.get("configurable") or {}
    ctx = configurable.get("ctx")
    if not isinstance(ctx, AgentContext):  # pragma: no cover - wiring guard
        raise RuntimeError("AgentContext missing from graph config['configurable']['ctx']")
    return ctx


def _classify_text(state: AgentState) -> str:
    if state.get("user_text"):
        return state["user_text"]
    event = state.get("event") or {}
    return str(event.get("summary") or event.get("type") or "")


async def supervisor_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Entry node: redact the turn, classify intent, append the user turn."""
    ctx = get_ctx(config)
    text = _classify_text(state)

    # Redaction map for the whole run (specialists restore tool args from it).
    ctx.redaction = ctx.redactor.redact(text)
    redacted_user = ctx.redaction.text

    await ctx.emit({"type": "agent", "agent": "supervisor", "node": "supervisor"})

    intent = await _classify(ctx, text)

    # Guard: specialist paths that need an existing customer fall back to acquisition.
    needs_customer = intent in ("adoption", "engagement")
    if needs_customer and ctx.customer_id is None and state.get("trigger") != "event":
        intent = "acquisition"

    messages: list[ChatTurn] = list(state.get("messages") or [])
    if state.get("trigger") == "event":
        messages.append(
            ChatTurn(role="user", content=f"[SYSTEM EVENT] {redacted_user}")
        )
    else:
        messages.append(ChatTurn(role="user", content=redacted_user))

    await ctx.audit_record(
        actor="supervisor",
        action="intent.classified",
        entity="conversation",
        entity_id=state.get("conversation_id"),
        payload={"intent": intent, "trigger": state.get("trigger")},
    )

    return {"intent": intent, "current_agent": "supervisor", "messages": messages}


async def _classify(ctx: AgentContext, text: str) -> str:
    started = perf_counter()
    try:
        resp = await ctx.router.chat(
            tier="fast",
            messages=[ChatMessage(role="user", content=text or "(empty)")],
            system=_CLASSIFIER_SYSTEM,
            json_mode=True,
            temperature=0.0,
            purpose="supervisor:classify",
        )
    except Exception:
        return _heuristic_intent(text)

    intent = _parse_intent(resp.text)
    await ctx.tracer.step(
        node="supervisor",
        kind=AgentStepKind.LLM,
        name="classify_intent",
        input={"text": text[:500]},
        output={"intent": intent, "raw": resp.text[:300]},
        model=resp.model,
        tokens_in=resp.tokens_in,
        tokens_out=resp.tokens_out,
        cost_usd=resp.cost_usd,
        latency_ms=int((perf_counter() - started) * 1000),
    )
    return intent


def _parse_intent(raw: str) -> str:
    try:
        data = orjson.loads(raw)
        intent = str(data.get("intent", "")).strip().lower()
        if intent in VALID_INTENTS:
            return intent
    except Exception:
        pass
    return _heuristic_intent(raw)


_ACQ_WORDS = ("open", "new account", "sign up", "onboard", "kyc", "register")
_ENG_WORDS = (
    "bonus", "raise", "new job", "married", "baby", "child", "home loan",
    "retire", "switch bank", "leaving",
)
_ADO_WORDS = ("upi", "autopay", "how do i", "balance", "activate", "netbanking", "card")


def _heuristic_intent(text: str) -> str:
    t = text.lower()
    if any(k in t for k in _ACQ_WORDS):
        return "acquisition"
    if any(k in t for k in _ENG_WORDS):
        return "engagement"
    if any(k in t for k in _ADO_WORDS):
        return "adoption"
    return "smalltalk"


def route_intent(state: AgentState) -> str:
    """Conditional-edge selector: map the classified intent to a node."""
    intent = state.get("intent", "smalltalk")
    return intent if intent in VALID_INTENTS else "smalltalk"


# ---------------------------------------------------------------------------
# Shared specialist runner (used by acquisition/adoption/engagement nodes)
# ---------------------------------------------------------------------------


async def run_specialist(
    state: AgentState,
    config: RunnableConfig,
    *,
    agent_name: str,
    node_name: str,
    system_builder: Any,
    tools: dict[str, Tool],
    tier: str = "smart",
) -> dict[str, Any]:
    """Gather context, run the specialist tool loop, stash the draft."""
    ctx = get_ctx(config)
    await ctx.emit({"type": "agent", "agent": agent_name, "node": node_name})

    profile: dict[str, Any] = {}
    memories: list[Any] = []
    if ctx.customer_id is not None:
        profile = await memory.profile_facts(ctx.session, ctx.customer_id)
        memories = await memory.recall(
            ctx.session, ctx.customer_id, _classify_text(state) or "profile", k=5
        )

    system = system_builder(ctx, state, profile, memories)
    draft = await run_agent_loop(
        ctx,
        state,
        agent_name=agent_name,
        node_name=node_name,
        system=system,
        tools=tools,
        history=list(state.get("messages") or []),
        tier=tier,
    )

    scratch = dict(state.get("scratch") or {})
    scratch["last_draft"] = draft
    scratch["suitability"] = {"income": profile.get("income"), "risk": profile.get("risk")}
    return {
        "current_agent": agent_name,
        "scratch": scratch,
        "proposals_out": state.get("proposals_out", []),
        "structured": state.get("structured", {}),
        "customer_id": state.get("customer_id"),
    }


# ---------------------------------------------------------------------------
# Small talk (direct answer, no tools)
# ---------------------------------------------------------------------------

_SMALLTALK_SYSTEM = """You are Sarathi, a warm, concise digital relationship manager for an \
Indian retail bank. Answer greetings and general questions helpfully in 1-3 sentences. Do \
not invent account details or make product promises. If the user needs an account action, \
gently offer to help with it."""


async def _preferred_language(ctx: AgentContext) -> str | None:
    """Look up the customer's chat-language preference (``None`` for prospects
    or when unset - the language directive then auto-detects)."""
    if ctx.customer_id is None:
        return None
    customer = await ctx.session.get(Customer, ctx.customer_id)
    return customer.preferred_language if customer is not None else None


async def smalltalk_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    ctx = get_ctx(config)
    await ctx.emit({"type": "agent", "agent": "smalltalk", "node": "smalltalk"})
    history = [
        ChatMessage(role=t["role"], content=t["content"])  # type: ignore[arg-type]
        for t in state.get("messages") or []
    ]
    preferred = await _preferred_language(ctx)
    system = f"{_SMALLTALK_SYSTEM}\n\n{language_directive(preferred)}"
    # The small-talk direct answer is user-facing, so it streams token-by-token on
    # the chat path (blocking on the event path). ``stream_final_answer`` traces
    # the call with real usage/cost.
    draft = await stream_final_answer(
        ctx,
        tier="fast",
        messages=history or [ChatMessage(role="user", content=state.get("user_text", "hello"))],
        system=system,
        purpose="smalltalk",
        node="smalltalk",
        name="smalltalk.answer",
    )
    scratch = dict(state.get("scratch") or {})
    scratch["last_draft"] = draft
    return {"current_agent": "smalltalk", "scratch": scratch}


# ---------------------------------------------------------------------------
# Synthesis / finalisation (policy + disclosures + audit + memory + streaming)
# ---------------------------------------------------------------------------


async def synthesize_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    ctx = get_ctx(config)
    scratch = dict(state.get("scratch") or {})
    raw_draft = scratch.get("last_draft") or ""
    draft = raw_draft or "How can I help you with your banking today?"

    suitability = scratch.get("suitability") or {}
    verdict = ctx.policy.check(draft, profile=suitability)
    final_text = verdict.fixed_text

    await ctx.tracer.step(
        node="synthesize",
        kind=AgentStepKind.GUARDRAIL,
        name="policy_check",
        input={"draft": draft[:1000]},
        output={
            "allowed": verdict.allowed,
            "violations": verdict.violations,
            "disclosures_added": verdict.disclosures_added,
        },
    )
    await ctx.audit_record(
        actor="supervisor",
        action="agent.response",
        entity="conversation",
        entity_id=state.get("conversation_id"),
        payload={
            "intent": state.get("intent"),
            "agent": state.get("current_agent"),
            "violations": verdict.violations,
            "disclosures": verdict.disclosures_added,
            "proposals": state.get("proposals_out", []),
        },
    )

    # Episodic memory of the turn (embedded if a provider is configured).
    if ctx.customer_id is not None:
        try:
            summary = (
                f"User said: {state.get('user_text', '')[:240]} | "
                f"Sarathi ({state.get('intent')}): {final_text[:240]}"
            )
            await memory.remember(
                ctx.session, ctx.customer_id, MemoryKind.EPISODIC, summary, embedder=ctx.embedder
            )
        except Exception:
            pass

    # The draft has already been streamed to the client token-by-token (real
    # provider deltas) by the specialist / small-talk node. Guardrails run on the
    # COMPLETE text here, so we only emit what policy *added* - mandated
    # disclosures are appended to the tail - to keep the incremental view in sync.
    # A policy *rewrite* (a blocked claim swapped inline) cannot be un-streamed,
    # so the authoritative corrected text rides the terminal ``done`` event's
    # ``final_text``, which the client uses to replace the streamed buffer.
    if ctx.emitter is not None:
        if not raw_draft:
            # Nothing was streamed (empty model output) - emit the fallback so the
            # incremental view still has content.
            await ctx.emit({"type": "token", "text": final_text})
        elif final_text.startswith(draft) and len(final_text) > len(draft):
            await ctx.emit({"type": "token", "text": final_text[len(draft):]})
    structured = state.get("structured") or {}
    if structured:
        await ctx.emit({"type": "structured", "data": structured})

    messages: list[ChatTurn] = list(state.get("messages") or [])
    messages.append(ChatTurn(role="assistant", content=final_text))
    return {"final_text": final_text, "messages": messages}


def _uuid_or_none(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError):
        return None
