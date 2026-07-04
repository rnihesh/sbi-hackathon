"""Adoption agent - drives feature usage for existing customers.

Detects dormancy signals deterministically (no UPI in 30 days, large idle
balance without an FD, protection gaps), then drafts nudges, proposes impactful
actions for HITL, or returns a structured product walkthrough the frontend
renders step-by-step.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.agents.actions import create_nudge, create_proposal
from app.agents.context import AgentContext
from app.agents.state import AgentState, append_proposal, append_structured, set_structured
from app.agents.supervisor import run_specialist
from app.agents.toolkit import Tool, ToolArgs, ToolResult, make_tool, obj_schema
from app.models.enums import ProposalKind, TxnChannel
from app.services import ledger, products

AGENT_NAME = "adoption"
NODE_NAME = "adoption"

_IDLE_THRESHOLD_PAISE = 50_000 * 100  # ₹50,000

# Structured, renderable walkthroughs (real product flows, not filler).
_WALKTHROUGHS: dict[str, dict[str, Any]] = {
    "upi_setup": {
        "title": "Set up UPI on your account",
        "steps": [
            "Open the bank app and tap 'UPI / BHIM'.",
            "Select this savings account as the linked account.",
            "Create a UPI PIN using your debit card's last 6 digits + expiry.",
            "Verify with the OTP sent to your registered mobile.",
            "Send ₹1 to yourself to confirm UPI is active.",
        ],
    },
    "autopay": {
        "title": "Enable UPI AutoPay for recurring bills",
        "steps": [
            "Go to 'Mandates' in the app and tap 'Create AutoPay'.",
            "Choose the biller (electricity, OTT, SIP, etc.).",
            "Set the max amount and frequency.",
            "Approve the mandate with your UPI PIN.",
        ],
    },
    "fd_booking": {
        "title": "Book a Fixed Deposit online",
        "steps": [
            "Open 'Deposits' → 'Open Fixed Deposit'.",
            "Enter the amount and choose a tenure.",
            "Pick the interest payout (cumulative or monthly).",
            "Confirm - the FD is created instantly from your savings balance.",
        ],
    },
    "netbanking": {
        "title": "Activate Netbanking",
        "steps": [
            "Visit the bank's netbanking portal and tap 'New User'.",
            "Enter your account number and registered mobile.",
            "Set a login password and a profile password.",
            "Log in and complete the security questions.",
        ],
    },
}


def _system(
    ctx: AgentContext, state: AgentState, profile: dict[str, Any], memories: list[Any]
) -> str:
    held = profile.get("held_product_codes") or []
    mem = "; ".join(m.text for m in memories[:3]) if memories else "none"
    return f"""You are Sarathi's adoption specialist for an existing Indian retail-bank \
customer. Help them actually use their banking: activate dormant features, adopt UPI/\
autopay/FD/netbanking, and act on idle money.

Guidance:
- Call get_usage_snapshot first to see real dormancy signals before advising.
- Use start_walkthrough for 'how do I…' requests (topics: upi_setup, autopay, fd_booking, \
netbanking) - the app renders the steps.
- Use draft_nudge for a gentle in-app suggestion.
- Use propose_action for impactful outreach (e.g. an email offer) - it goes to a human \
approval queue, it does NOT send automatically.
Keep replies concrete and encouraging. Customer holds: {held}. Recent context: {mem}."""


async def _get_usage_snapshot(ctx: AgentContext, state: AgentState, args: ToolArgs) -> ToolResult:
    if ctx.customer_id is None:
        return {"error": "no customer in context"}
    cid = ctx.customer_id
    days = int(args.get("days", 30) or 30)
    txns = await ledger.get_recent_transactions(ctx.session, cid, days)
    balance = await ledger.get_customer_balance(ctx.session, cid)
    held = await products.held_product_codes(ctx.session, cid)

    channels = {t.channel.value for t in txns}
    has_upi = TxnChannel.UPI.value in channels
    has_fd = "fixed_deposit" in held
    has_insurance = any(c in held for c in ("term_insurance", "personal_accident_cover"))

    signals: list[str] = []
    if not has_upi:
        signals.append(f"no UPI transactions in the last {days} days")
    if balance > _IDLE_THRESHOLD_PAISE and not has_fd:
        signals.append(f"~₹{balance // 100:,} idle in savings with no fixed deposit")
    if not has_insurance:
        signals.append("no protection cover (term/accident) on file")
    if not txns:
        signals.append(f"no transactions at all in the last {days} days (dormant account)")

    return {
        "window_days": days,
        "transaction_count": len(txns),
        "balance_paise": balance,
        "channels_used": sorted(channels),
        "held_products": held,
        "has_upi": has_upi,
        "has_fd": has_fd,
        "has_insurance": has_insurance,
        "dormancy_signals": signals,
    }


async def _draft_nudge(ctx: AgentContext, state: AgentState, args: ToolArgs) -> ToolResult:
    if ctx.customer_id is None:
        return {"error": "no customer in context"}
    nudge = await create_nudge(
        ctx.session,
        customer_id=ctx.customer_id,
        title=str(args.get("title", "A quick suggestion")),
        body=str(args.get("body", "")),
        cta=args.get("cta") if isinstance(args.get("cta"), dict) else {"label": args.get("cta")},
    )
    await ctx.audit_record(
        "adoption", "nudge.created", "nudge", str(nudge.id), {"title": nudge.title},
    )
    append_structured(state, "nudges", str(nudge.id))
    return {"nudge_id": str(nudge.id), "delivered": "in_app"}


async def _propose_action(ctx: AgentContext, state: AgentState, args: ToolArgs) -> ToolResult:
    if ctx.customer_id is None:
        return {"error": "no customer in context"}
    kind = str(args.get("kind", "action"))
    raw_action = args.get("action")
    action: dict[str, Any] = dict(raw_action) if isinstance(raw_action, dict) else {}
    action.setdefault("kind", str(args.get("action_kind", "send_nudge")))
    proposal = await create_proposal(
        ctx.session,
        customer_id=ctx.customer_id,
        agent="adoption",
        kind=ProposalKind(kind) if kind in {k.value for k in ProposalKind} else ProposalKind.ACTION,
        title=str(args.get("title", "Proposed action")),
        body=str(args.get("body", "")),
        action=action,
    )
    await ctx.audit_record(
        "adoption", "proposal.created", "proposal", str(proposal.id),
        {"kind": proposal.kind.value, "action": action.get("kind")},
    )
    append_proposal(state, str(proposal.id))
    return {"proposal_id": str(proposal.id), "status": "pending_approval"}


async def _start_walkthrough(ctx: AgentContext, state: AgentState, args: ToolArgs) -> ToolResult:
    topic = str(args.get("topic", "")).lower()
    walkthrough = _WALKTHROUGHS.get(topic)
    if walkthrough is None:
        return {"error": f"unknown topic '{topic}'", "available": list(_WALKTHROUGHS)}
    payload = {"topic": topic, **walkthrough}
    set_structured(state, "walkthrough", payload)
    return payload


def build_tools() -> dict[str, Tool]:
    tools = [
        make_tool(
            "get_usage_snapshot", "Compute the customer's real dormancy/usage signals.",
            obj_schema({"days": {"type": "integer", "description": "lookback window"}}),
            _get_usage_snapshot,
        ),
        make_tool(
            "draft_nudge", "Create an in-app nudge for the customer (immediate).",
            obj_schema({
                "title": {"type": "string"},
                "body": {"type": "string"},
                "cta": {"type": "object"},
            }, required=["title", "body"]),
            _draft_nudge,
        ),
        make_tool(
            "propose_action", "Propose an impactful action for human approval (not sent now).",
            obj_schema({
                "kind": {"type": "string", "enum": ["email", "product_offer", "action", "nudge"]},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "action": {"type": "object", "description": "executable payload incl. 'kind'"},
            }, required=["title", "body"]),
            _propose_action,
        ),
        make_tool(
            "start_walkthrough", "Return a structured, step-by-step product walkthrough.",
            obj_schema({
                "topic": {"type": "string", "enum": list(_WALKTHROUGHS)},
            }, required=["topic"]),
            _start_walkthrough,
        ),
    ]
    return {t.name: t for t in tools}


_TOOLS = build_tools()


async def adoption_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    return await run_specialist(
        state, config,
        agent_name=AGENT_NAME, node_name=NODE_NAME,
        system_builder=_system, tools=_TOOLS,
    )
