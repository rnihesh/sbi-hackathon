"""Acquisition agent - SBI-style onboarding relationship manager.

Runs genuine multi-turn onboarding: creates a lead, scores intent, collects and
validates KYC fields progressively, verifies KYC, matches products, and opens an
account. The **open-account KYC gate is enforced in code** (:func:`_open_account`),
not merely in the prompt - the account cannot be opened until KYC status is
``verified``, whatever the LLM tries.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.agents import memory
from app.agents.context import AgentContext
from app.agents.state import AgentState, set_structured
from app.agents.supervisor import run_specialist
from app.agents.toolkit import Tool, ToolArgs, ToolResult, make_tool, obj_schema
from app.models.crm import Lead
from app.models.customer import Customer
from app.models.enums import LeadStage, MemoryKind, NotificationKind
from app.services import kyc, ledger
from app.services.notifications import notify
from app.services.products import CustomerProfile, rank_products

_PHONE_RE = re.compile(r"^(?:\+91[\-\s]?|0)?[6-9]\d{9}$")
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

_KYC_ORDER = ("name", "phone", "email", "pan", "address")

AGENT_NAME = "acquisition"
NODE_NAME = "acquisition"


def _system(
    ctx: AgentContext, state: AgentState, profile: dict[str, Any], memories: list[Any]
) -> str:
    kyc_state = (state.get("scratch") or {}).get("kyc", {})
    collected = [f for f in _KYC_ORDER if kyc_state.get(f)]
    status = kyc_state.get("status", "not_started")
    return f"""You are Sarathi's onboarding relationship manager for an Indian retail bank \
(SBI-style). Warmly guide a prospect to open an account. Be concise, friendly, and \
compliant.

Your job, in order:
1. Create a lead (create_lead) early, using whatever contact info is shared.
2. Collect KYC ONE field at a time using collect_kyc_field: {', '.join(_KYC_ORDER)}. Never \
ask for more than one at once. PAN format is ABCDE1234F.
3. Once name + PAN are collected, call verify_kyc.
4. Only AFTER KYC status is 'verified', call open_account (savings by default). If not \
verified, do NOT promise an account - explain what is pending.
5. Optionally call match_products to suggest suitable next products, and score_intent to \
record buying intent.

Current onboarding state: collected={collected}, kyc_status={status}. Ask only for what is \
still missing. Do not fabricate PAN/Aadhaar or account numbers."""


# ---------------------------------------------------------------------------
# tool implementations
# ---------------------------------------------------------------------------


def _scratch(state: AgentState) -> dict[str, Any]:
    scratch = state.get("scratch")
    if scratch is None:
        scratch = {}
        state["scratch"] = scratch
    return scratch


def _kyc_bag(state: AgentState) -> dict[str, Any]:
    scratch = _scratch(state)
    bag = scratch.get("kyc")
    if not isinstance(bag, dict):
        bag = {}
        scratch["kyc"] = bag
    return bag


async def _create_lead(ctx: AgentContext, state: AgentState, args: ToolArgs) -> ToolResult:
    lead = Lead(
        source=str(args.get("source", "chat")),
        name=args.get("name"),
        email=args.get("email"),
        phone=args.get("phone"),
        notes=args.get("notes"),
        stage=LeadStage.NEW,
        customer_id=ctx.customer_id,
    )
    ctx.session.add(lead)
    await ctx.session.flush()
    _scratch(state)["lead_id"] = str(lead.id)
    await ctx.audit_record(
        "acquisition", "lead.created", "lead", str(lead.id),
        {"source": lead.source, "has_contact": bool(lead.email or lead.phone)},
    )
    return {"lead_id": str(lead.id), "stage": lead.stage.value, "created": True}


async def _score_intent(ctx: AgentContext, state: AgentState, args: ToolArgs) -> ToolResult:
    # LLM assesses signals; this tool converts them to a reproducible score.
    weights = {
        "explicit_interest": 0.4,
        "provided_contact": 0.2,
        "product_specific": 0.2,
    }
    score = sum(w for key, w in weights.items() if bool(args.get(key)))
    urgency = str(args.get("urgency", "low")).lower()
    score += {"high": 0.2, "medium": 0.1}.get(urgency, 0.0)
    score = round(min(score, 1.0), 3)

    lead_id = (state.get("scratch") or {}).get("lead_id")
    if lead_id:
        lead = await ctx.session.get(Lead, uuid.UUID(lead_id))
        if lead is not None:
            lead.intent_score = score
            if score >= 0.6:
                lead.stage = LeadStage.QUALIFIED
            await ctx.session.flush()
    return {"intent_score": score, "urgency": urgency}


def _validate_field(field: str, value: str) -> tuple[bool, str]:
    field = field.lower()
    value = value.strip()
    if field == "name":
        return (len(value) >= 2, "name recorded" if len(value) >= 2 else "name too short")
    if field == "phone":
        ok = bool(_PHONE_RE.match(value))
        return ok, "phone recorded" if ok else "invalid Indian mobile number"
    if field == "email":
        ok = bool(_EMAIL_RE.match(value))
        return ok, "email recorded" if ok else "invalid email format"
    if field == "pan":
        ok = kyc.validate_pan(value)
        return ok, "PAN format valid" if ok else "invalid PAN (expected ABCDE1234F)"
    if field == "aadhaar":
        ok = kyc.validate_aadhaar(value)
        return ok, "Aadhaar valid" if ok else "invalid Aadhaar (checksum failed)"
    if field == "address":
        return (len(value) >= 5, "address recorded" if len(value) >= 5 else "address too short")
    return False, f"unknown field '{field}'"


async def _collect_kyc_field(ctx: AgentContext, state: AgentState, args: ToolArgs) -> ToolResult:
    field = str(args.get("field", "")).lower()
    value = str(args.get("value", ""))
    valid, message = _validate_field(field, value)
    bag = _kyc_bag(state)
    if valid:
        bag[field] = value.strip().upper() if field == "pan" else value.strip()
    collected = [f for f in (*_KYC_ORDER, "aadhaar") if bag.get(f)]
    remaining = [f for f in _KYC_ORDER if not bag.get(f)]
    return {
        "field": field,
        "valid": valid,
        "message": message,
        "collected": collected,
        "next_needed": remaining[0] if remaining else None,
        "ready_to_verify": bool(bag.get("name") and bag.get("pan")),
    }


async def _verify_kyc(ctx: AgentContext, state: AgentState, args: ToolArgs) -> ToolResult:
    bag = _kyc_bag(state)
    name = bag.get("name")
    pan = bag.get("pan")
    if not (name and pan):
        return {"error": "cannot verify: name and PAN are required first",
                "status": "incomplete"}
    result = await kyc.verify(
        name=name, pan=pan, aadhaar=bag.get("aadhaar"),
        official_name=args.get("official_name"),
    )
    bag["status"] = result.status.value
    await ctx.audit_record(
        "acquisition", "kyc.verified", "lead", (state.get("scratch") or {}).get("lead_id"),
        {"status": result.status.value, "reason": result.reason},
    )
    return result.as_dict()


async def _match_products(ctx: AgentContext, state: AgentState, args: ToolArgs) -> ToolResult:
    bag = _kyc_bag(state)
    profile = CustomerProfile(
        annual_income_paise=args.get("annual_income_paise"),
        age=args.get("age"),
        segment=args.get("segment"),
        dependents=int(args.get("dependents", 0) or 0),
        held_product_codes=[],
        risk_appetite=args.get("risk_appetite"),
    )
    candidates = await rank_products(
        profile, router=ctx.router, limit=int(args.get("limit", 4) or 4)
    )
    offers = [c.as_dict() for c in candidates]
    # Surface offers as structured payload so the frontend renders real offer
    # cards instead of relying on the model summarizing them into prose.
    set_structured(state, "offers", offers)
    return {"candidates": offers, "kyc_status": bag.get("status")}


async def _open_account(ctx: AgentContext, state: AgentState, args: ToolArgs) -> ToolResult:
    """Open an account - ENFORCED KYC gate lives here, not in the prompt."""
    bag = _kyc_bag(state)
    if bag.get("status") != "verified":
        return {
            "opened": False,
            "error": "KYC not verified - account cannot be opened",
            "kyc_status": bag.get("status", "not_started"),
        }

    customer = await _ensure_customer(ctx, state)
    account_type = str(args.get("account_type", "savings"))
    # Accept the deposit in paise, or convert from rupees if that's what was passed.
    if args.get("initial_deposit_paise") is not None:
        initial = int(args.get("initial_deposit_paise") or 0)
    else:
        initial = int(args.get("initial_deposit_rupees") or 0) * 100

    account = await ledger.open_account(
        ctx.session,
        customer_id=customer.id,
        account_type=account_type,
        initial_deposit_paise=initial,
        label=args.get("label"),
    )

    # Convert the lead.
    lead_id = (state.get("scratch") or {}).get("lead_id")
    if lead_id:
        lead = await ctx.session.get(Lead, uuid.UUID(lead_id))
        if lead is not None:
            lead.stage = LeadStage.CONVERTED
            lead.customer_id = customer.id
            await ctx.session.flush()

    await ctx.audit_record(
        "acquisition", "account.opened", "account", str(account.id),
        {"customer_id": str(customer.id), "type": account_type, "initial_paise": initial},
    )
    await notify(
        ctx.session,
        customer.id,
        NotificationKind.ACCOUNT,
        "Your account is open",
        f"Your new {account_type.replace('_', ' ')} account is ready to use.",
        link="/app/home",
    )
    return {
        "opened": True,
        "account_id": str(account.id),
        "customer_id": str(customer.id),
        "type": account_type,
        "balance_paise": account.balance_paise,
    }


async def _ensure_customer(ctx: AgentContext, state: AgentState) -> Customer:
    """Return the run's customer, creating one from collected KYC if needed."""
    if ctx.customer_id is not None:
        existing = await ctx.session.get(Customer, ctx.customer_id)
        if existing is not None:
            return existing
    bag = _kyc_bag(state)
    customer = Customer(
        full_name=bag.get("name", "New Customer"),
        email=bag.get("email"),
        phone=bag.get("phone"),
    )
    ctx.session.add(customer)
    await ctx.session.flush()
    ctx.customer_id = customer.id
    state["customer_id"] = str(customer.id)
    ctx.conversation_id = ctx.conversation_id or state.get("conversation_id")
    return customer


async def _record_memory(ctx: AgentContext, state: AgentState, args: ToolArgs) -> ToolResult:
    if ctx.customer_id is None:
        # No customer yet - stash on the lead notes instead.
        lead_id = (state.get("scratch") or {}).get("lead_id")
        if lead_id:
            lead = await ctx.session.get(Lead, uuid.UUID(lead_id))
            if lead is not None:
                lead.notes = f"{lead.notes or ''}\n{args.get('text', '')}".strip()
                await ctx.session.flush()
        return {"stored": "lead_note"}
    kind = str(args.get("kind", "fact"))
    await memory.remember(
        ctx.session, ctx.customer_id,
        MemoryKind(kind) if kind in {k.value for k in MemoryKind} else MemoryKind.FACT,
        str(args.get("text", "")), embedder=ctx.embedder,
    )
    return {"stored": "memory"}


def build_tools() -> dict[str, Tool]:
    tools = [
        make_tool(
            "create_lead", "Create a sales lead for this prospect.",
            obj_schema({
                "source": {"type": "string", "description": "lead source, e.g. 'chat'"},
                "name": {"type": "string"},
                "email": {"type": "string"},
                "phone": {"type": "string"},
                "notes": {"type": "string"},
            }),
            _create_lead,
        ),
        make_tool(
            "score_intent", "Record the prospect's buying intent from observed signals.",
            obj_schema({
                "explicit_interest": {"type": "boolean"},
                "provided_contact": {"type": "boolean"},
                "product_specific": {"type": "boolean"},
                "urgency": {"type": "string", "enum": ["low", "medium", "high"]},
            }),
            _score_intent,
        ),
        make_tool(
            "collect_kyc_field", "Validate and store a single KYC field.",
            obj_schema({
                "field": {"type": "string", "enum": [*_KYC_ORDER, "aadhaar"]},
                "value": {"type": "string"},
            }, required=["field", "value"]),
            _collect_kyc_field,
        ),
        make_tool(
            "verify_kyc", "Run KYC verification once name and PAN are collected.",
            obj_schema({"official_name": {"type": "string"}}),
            _verify_kyc,
        ),
        make_tool(
            "match_products", "Rank suitable products for the prospect.",
            obj_schema({
                "annual_income_paise": {"type": "integer"},
                "age": {"type": "integer"},
                "segment": {"type": "string", "enum": ["salaried", "business"]},
                "dependents": {"type": "integer"},
                "risk_appetite": {"type": "string"},
                "limit": {"type": "integer"},
            }),
            _match_products,
        ),
        make_tool(
            "open_account", "Open an account (only allowed after KYC is verified).",
            obj_schema({
                "account_type": {
                    "type": "string",
                    "enum": ["savings", "current", "salary", "fixed_deposit", "recurring_deposit"],
                },
                "initial_deposit_rupees": {"type": "integer"},
                "label": {"type": "string"},
            }),
            _open_account,
        ),
        make_tool(
            "record_memory", "Persist a durable fact/preference about this prospect.",
            obj_schema({
                "kind": {"type": "string", "enum": ["fact", "preference", "episodic"]},
                "text": {"type": "string"},
            }, required=["text"]),
            _record_memory,
        ),
    ]
    return {t.name: t for t in tools}


_TOOLS = build_tools()


async def acquisition_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    return await run_specialist(
        state, config,
        agent_name=AGENT_NAME, node_name=NODE_NAME,
        system_builder=_system, tools=_TOOLS,
    )
