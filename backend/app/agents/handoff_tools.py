"""Human-handoff agent tool + the deterministic escalation backstop.

The star capability of the demo: Sarathi knowing when to step aside. Every
specialist (acquisition/adoption/engagement) shares one tool,
``request_human_handoff``, which queues a :class:`~app.models.handoff.HandoffRequest`
row for the console handoff queue, notifies an authenticated customer, and
surfaces the handoff on the run's structured output (so the live feed can
publish it after commit). It never sends anything itself - it hands the
conversation to a person.

Two escalation drivers, layered:

1. **LLM-driven** (soft): :data:`HANDOFF_TOOL_GUIDANCE` is appended to every
   specialist system prompt so the model escalates for the nuanced cases
   (frustration after repeated failures, requests beyond agent authority).
2. **Deterministic backstop** (hard): :func:`handoff_backstop_triggered` matches
   unambiguous phrases (English + Hindi/Hinglish). When it fires the chat
   entrypoint routes to a tool-capable specialist and injects
   :data:`HANDOFF_BACKSTOP_NUDGE` - a stronger instruction to call the tool now.
   It never auto-creates the row: the LLM still calls the tool with a proper,
   summarised reason.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.agents.context import AgentContext
from app.agents.state import AgentState, append_structured
from app.agents.toolkit import Tool, ToolArgs, ToolResult, make_tool, obj_schema
from app.models.enums import HandoffStatus, HandoffUrgency, NotificationKind
from app.models.handoff import HandoffRequest
from app.services.notifications import notify

_VALID_URGENCY = tuple(u.value for u in HandoffUrgency)

# Appended to every specialist system prompt: when to step aside for a human.
HANDOFF_TOOL_GUIDANCE = (
    "You can escalate to a human relationship manager with the request_human_handoff "
    "tool. Escalate when the user explicitly asks for a human/agent/person, is frustrated "
    "after repeated failed attempts, raises a complaint or dispute, reports fraud, or asks "
    "for something outside your authority (closing an account, reporting fraud, large or "
    "unusual transfers). Pass a short reason that summarises what they need and set urgency "
    "(low/normal/high; use high for fraud, disputes, or an upset customer). Do NOT escalate "
    "for routine questions you can answer yourself. After the tool runs, warmly reassure the "
    "user that a relationship manager will reach out."
)

# Stronger nudge, injected ONLY when the deterministic backstop fires.
HANDOFF_BACKSTOP_NUDGE = (
    "IMPORTANT: the user's latest message strongly signals they want a human, or is a "
    "complaint or fraud concern. Unless you are certain you can fully resolve it yourself "
    "right now, call request_human_handoff with a clear reason before replying."
)

# Case-insensitive substrings that force the handoff nudge. Kept deliberately
# unambiguous (a hard safety net), not an exhaustive intent classifier - the
# LLM guidance above covers the nuanced cases.
_BACKSTOP_PATTERNS: tuple[str, ...] = (
    "talk to a human",
    "talk to a person",
    "talk to a agent",
    "talk to an agent",
    "talk to a real",
    "speak to a human",
    "speak to a person",
    "speak to someone",
    "speak to an agent",
    "speak to a real",
    "real person",
    "human agent",
    "complaint",
    "fraud",
    # Hindi / Hinglish
    "insaan se baat",
    "shikayat",
)


def handoff_backstop_triggered(text: str | None) -> bool:
    """True when ``text`` unambiguously asks for a human / raises a complaint.

    Case-insensitive substring match. Deterministic (no LLM), so the chat
    entrypoint can rely on it to guarantee the handoff nudge is in context.
    """
    if not text:
        return False
    lowered = text.lower()
    return any(pattern in lowered for pattern in _BACKSTOP_PATTERNS)


def _coerce_urgency(value: Any) -> HandoffUrgency:
    raw = str(value or "").strip().lower()
    if raw in _VALID_URGENCY:
        return HandoffUrgency(raw)
    return HandoffUrgency.NORMAL


def build_handoff_tools(agent_name: str) -> list[Tool]:
    """Return the shared ``request_human_handoff`` tool, wired to ``agent_name``."""

    async def _request_human_handoff(
        ctx: AgentContext, state: AgentState, args: ToolArgs
    ) -> ToolResult:
        conversation_id = ctx.conversation_id or state.get("conversation_id") or ""

        # Guard: one active handoff per conversation. If one is already open or
        # claimed, report its status instead of queuing a duplicate.
        existing = await ctx.session.scalar(
            select(HandoffRequest)
            .where(
                HandoffRequest.conversation_id == conversation_id,
                HandoffRequest.status != HandoffStatus.RESOLVED,
            )
            .order_by(HandoffRequest.created_at.desc())
            .limit(1)
        )
        if existing is not None:
            return {
                "created": False,
                "duplicate": True,
                "handoff_id": str(existing.id),
                "status": existing.status.value,
                "urgency": existing.urgency.value,
                "message": (
                    "A relationship manager is already lined up for this conversation - "
                    "no need to ask twice."
                ),
            }

        reason = str(args.get("reason", "")).strip()[:500]
        if not reason:
            reason = "Customer asked to speak with a human relationship manager."
        urgency = _coerce_urgency(args.get("urgency"))

        handoff = HandoffRequest(
            customer_id=ctx.customer_id,
            conversation_id=conversation_id,
            reason=reason,
            urgency=urgency,
            status=HandoffStatus.OPEN,
        )
        ctx.session.add(handoff)
        await ctx.session.flush()

        await ctx.audit_record(
            agent_name,
            "handoff.requested",
            "handoff_request",
            str(handoff.id),
            {"urgency": urgency.value, "authenticated": ctx.customer_id is not None},
        )

        # Notify an authenticated customer that a human is coming (anon prospects
        # have no inbox - they see the in-chat card instead).
        if ctx.customer_id is not None:
            await notify(
                ctx.session,
                ctx.customer_id,
                NotificationKind.SYSTEM,
                "A relationship manager will reach out",
                "We've asked one of our relationship managers to follow up with you "
                "personally. They'll be in touch shortly.",
            )

        # Surface on the run's structured output so the console live feed can
        # publish a `handoff` envelope after the turn commits (mirrors how
        # proposals/nudges reach the feed).
        append_structured(
            state,
            "handoffs",
            {"id": str(handoff.id), "urgency": urgency.value, "reason": reason},
        )

        return {
            "created": True,
            "handoff_id": str(handoff.id),
            "status": handoff.status.value,
            "urgency": urgency.value,
            "reason": reason,
            "message": (
                "A relationship manager has been asked to reach out. Reassure the "
                "customer warmly that a human will follow up shortly."
            ),
        }

    return [
        make_tool(
            "request_human_handoff",
            "Escalate this conversation to a human relationship manager. Use when the user "
            "asks for a human, is frustrated after repeated failures, raises a complaint or "
            "fraud concern, or wants something outside your authority.",
            obj_schema(
                {
                    "reason": {
                        "type": "string",
                        "description": "short summary of what the user needs a human for",
                    },
                    "urgency": {
                        "type": "string",
                        "enum": list(_VALID_URGENCY),
                        "description": "how quickly a human should pick this up",
                    },
                },
                required=["reason"],
            ),
            _request_human_handoff,
        ),
    ]
