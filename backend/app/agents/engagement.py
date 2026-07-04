"""Engagement agent - life-event detection, next-best-action, churn.

``analyze_window`` extracts features **deterministically in code** (salary source
& amount, salary change, recurring merchants, category deltas, balance trend,
merchant-group hints). ``detect_life_events`` then runs an LLM (JSON mode) over
those features to propose typed candidates; ``record_life_event`` persists them;
``propose_outreach`` creates a HITL proposal; ``score_churn`` blends feature
signals with an LLM read and writes ``customer.churn_risk``.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from time import perf_counter
from typing import Any

import orjson
from langchain_core.runnables import RunnableConfig

from app.agents.actions import create_proposal, normalize_action_kind
from app.agents.context import AgentContext
from app.agents.language import language_directive
from app.agents.state import AgentState, append_proposal, append_structured
from app.agents.supervisor import run_specialist
from app.agents.toolkit import Tool, ToolArgs, ToolResult, make_tool, obj_schema
from app.llm.base import ChatMessage
from app.models.customer import Customer
from app.models.engagement import LifeEvent
from app.models.enums import (
    AgentStepKind,
    LifeEventStatus,
    LifeEventType,
    NotificationKind,
    ProposalKind,
)
from app.services import ledger
from app.services.notifications import notify

AGENT_NAME = "engagement"
NODE_NAME = "engagement"

_INCOME_CATEGORIES = {
    "salary", "pension", "business_inflow", "gig_payout",
    "pocket_money", "household_allowance",
}
_MERCHANT_GROUPS: dict[str, tuple[str, ...]] = {
    "baby": ("firstcry", "mothercare", "babychakra", "baby"),
    "wedding": ("tanishq", "kalyan", "malabar", "caterer", "banquet", "convention", "jewel"),
    "home": ("builder", "home loan", "realty", "properties", "construction"),
    "travel": ("makemytrip", "irctc", "indigo", "vistara", "goibibo", "airbnb"),
}
_LIFE_EVENT_VALUES = [e.value for e in LifeEventType]

# Warm, factual phrasing for the customer notification (never overclaims - each
# is a "possible"/"signs of" read on their own activity, not a certainty).
_LIFE_EVENT_PHRASE: dict[str, str] = {
    "job_change": "signs of a job change",
    "new_child": "signs of a new addition to your family",
    "home_intent": "signs you may be planning for a home",
    "bonus": "a possible bonus in your activity",
    "salary_hike": "signs your income may have grown",
    "marriage": "signs of wedding planning",
    "relocation": "signs you may be relocating",
    "travel": "signs of upcoming travel",
}


def _features_json(features: dict[str, Any]) -> str:
    return orjson.dumps(features, default=str).decode()


def _system(
    ctx: AgentContext, state: AgentState, profile: dict[str, Any], memories: list[Any]
) -> str:
    return f"""You are Sarathi's engagement specialist for an Indian retail bank. You spot \
meaningful life events from a customer's banking behaviour and offer a timely, tasteful \
next-best-action - never pushy.

Workflow:
1. Call analyze_window to get deterministic behavioural features.
2. Call detect_life_events to identify candidates (types: {', '.join(_LIFE_EVENT_VALUES)}).
3. For a confident, relevant event, call record_life_event, then propose_outreach with a \
warm congratulation and ONE well-matched product (goes to human approval, not sent now).
4. If churn/leaving signals appear, call score_churn.

Be genuinely helpful and concise. Respect suitability - don't push investments without \
income and risk on file.

{language_directive(profile.get("preferred_language"))}"""


# ---------------------------------------------------------------------------
# deterministic feature extraction
# ---------------------------------------------------------------------------


async def _analyze_window(ctx: AgentContext, state: AgentState, args: ToolArgs) -> ToolResult:
    if ctx.customer_id is None:
        return {"error": "no customer in context"}
    days = int(args.get("days", 90) or 90)
    txns = await ledger.get_recent_transactions(ctx.session, ctx.customer_id, days)
    return extract_features(
        [
            {
                "ts": t.ts,
                "amount_paise": t.amount_paise,
                "direction": t.direction.value,
                "channel": t.channel.value,
                "merchant": t.merchant,
                "category": t.category,
                "balance_after_paise": t.balance_after_paise,
            }
            for t in txns
        ],
        days=days,
    )


def extract_features(txns: list[dict[str, Any]], *, days: int) -> dict[str, Any]:
    """Pure feature extraction over a transaction list (chronological-agnostic).

    Deterministic and side-effect free so it is unit-testable without a DB or LLM.
    """
    ordered = sorted(txns, key=lambda t: t["ts"])
    n = len(ordered)
    credits = [t for t in ordered if t["direction"] == "credit"]
    income = [t for t in credits if (t.get("category") or "") in _INCOME_CATEGORIES]

    # Salary detection + change.
    income_amounts = [t["amount_paise"] for t in income]
    salary_detected = bool(income)
    salary_amount = income_amounts[-1] if income_amounts else None
    salary_source = income[-1]["merchant"] if income else None
    change_pct: float | None = None
    direction: str | None = None
    if len(income_amounts) >= 2:
        first, last = income_amounts[0], income_amounts[-1]
        if first > 0:
            change_pct = round((last - first) / first, 3)
            if change_pct >= 0.15:
                direction = "up"
            elif change_pct <= -0.15:
                direction = "down"
            else:
                direction = "flat"

    # Recurring merchants (>= 3 occurrences).
    merchant_counts = Counter(t["merchant"] for t in ordered if t.get("merchant"))
    recurring = [
        {"merchant": m, "count": c} for m, c in merchant_counts.most_common() if c >= 3
    ]

    # Category deltas: first vs second half of the window.
    mid = n // 2
    first_half, second_half = ordered[:mid], ordered[mid:]

    def _by_cat(rows: list[dict[str, Any]]) -> dict[str, int]:
        acc: dict[str, int] = defaultdict(int)
        for r in rows:
            if r["direction"] == "debit" and r.get("category"):
                acc[r["category"]] += r["amount_paise"]
        return acc

    fh, sh = _by_cat(first_half), _by_cat(second_half)
    category_deltas = {
        cat: {"first_paise": fh.get(cat, 0), "second_paise": sh.get(cat, 0),
              "delta_paise": sh.get(cat, 0) - fh.get(cat, 0)}
        for cat in sorted(set(fh) | set(sh))
    }

    # Balance trend.
    balance_trend: dict[str, Any] = {}
    if ordered:
        start_bal = ordered[0]["balance_after_paise"]
        end_bal = ordered[-1]["balance_after_paise"]
        change = end_bal - start_bal
        balance_trend = {
            "start_paise": start_bal,
            "end_paise": end_bal,
            "change_paise": change,
            "direction": "up" if change > 0 else "down" if change < 0 else "flat",
        }

    # Windfall detection: a credit >= 2x the median income credit.
    large_credits: list[dict[str, Any]] = []
    if income_amounts:
        median_income = statistics.median(income_amounts)
        for c in credits:
            cat = c.get("category") or ""
            if c["amount_paise"] >= 2 * median_income and cat not in _INCOME_CATEGORIES:
                large_credits.append(
                    {"amount_paise": c["amount_paise"], "merchant": c.get("merchant"),
                     "category": c.get("category")}
                )

    # Merchant-group hints for life events.
    hints: dict[str, int] = dict.fromkeys(_MERCHANT_GROUPS, 0)
    for t in ordered:
        blob = f"{(t.get('merchant') or '')} {(t.get('category') or '')}".lower()
        for group, needles in _MERCHANT_GROUPS.items():
            if any(nd in blob for nd in needles):
                hints[group] += 1

    upi_count = sum(1 for t in ordered if t["channel"] == "upi")
    drain_present = any((t.get("category") or "") == "balance_drain" for t in ordered)

    return {
        "window_days": days,
        "transaction_count": n,
        "salary": {
            "detected": salary_detected,
            "amount_paise": salary_amount,
            "source": salary_source,
            "credits_paise": income_amounts,
            "change_pct": change_pct,
            "direction": direction,
        },
        "recurring_merchants": recurring,
        "category_deltas": category_deltas,
        "balance_trend": balance_trend,
        "large_credits": large_credits,
        "merchant_group_hints": {k: v for k, v in hints.items() if v > 0},
        "upi_txn_count": upi_count,
        "balance_drain_present": drain_present,
    }


# ---------------------------------------------------------------------------
# LLM detection over features
# ---------------------------------------------------------------------------

_DETECT_SYSTEM = f"""You detect life events from a customer's banking features. Given the \
JSON features, return candidates as JSON: {{"candidates": [{{"type": "<one of \
{', '.join(_LIFE_EVENT_VALUES)}>", "confidence": 0.0-1.0, "evidence": "<short reason citing \
the features>"}}]}}. Only include events with real support in the features. Return an empty \
list if none. Respond with ONLY the JSON object."""


async def _detect_life_events(ctx: AgentContext, state: AgentState, args: ToolArgs) -> ToolResult:
    features = args.get("features")
    if not isinstance(features, dict):
        features = await _analyze_window(ctx, state, {"days": int(args.get("days", 90) or 90)})
    started = perf_counter()
    try:
        resp = await ctx.router.chat(
            tier="smart",
            messages=[ChatMessage(role="user", content=_features_json(features))],
            system=_DETECT_SYSTEM,
            json_mode=True,
            temperature=0.0,
            purpose="engagement:detect_life_events",
        )
    except Exception as exc:
        return {"candidates": [], "error": str(exc)}

    candidates = _parse_candidates(resp.text)
    await ctx.tracer.step(
        node=NODE_NAME,
        kind=AgentStepKind.LLM,
        name="detect_life_events.llm",
        input={"feature_keys": sorted(features.keys())},
        output={"candidates": candidates},
        model=resp.model,
        tokens_in=resp.tokens_in,
        tokens_out=resp.tokens_out,
        cost_usd=resp.cost_usd,
        latency_ms=int((perf_counter() - started) * 1000),
    )
    return {"candidates": candidates}


def _parse_candidates(raw: str) -> list[dict[str, Any]]:
    try:
        data = orjson.loads(raw)
    except Exception:
        return []
    items = data.get("candidates", []) if isinstance(data, dict) else []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        etype = str(item.get("type", "")).lower()
        if etype not in _LIFE_EVENT_VALUES:
            continue
        out.append({
            "type": etype,
            "confidence": float(item.get("confidence", 0.0) or 0.0),
            "evidence": str(item.get("evidence", "")),
        })
    return out


async def _record_life_event(ctx: AgentContext, state: AgentState, args: ToolArgs) -> ToolResult:
    if ctx.customer_id is None:
        return {"error": "no customer in context"}
    etype = str(args.get("type", "")).lower()
    if etype not in _LIFE_EVENT_VALUES:
        return {"error": f"unknown life event type '{etype}'", "allowed": _LIFE_EVENT_VALUES}
    evidence = args.get("evidence")
    event = LifeEvent(
        customer_id=ctx.customer_id,
        type=LifeEventType(etype),
        confidence=float(args.get("confidence", 0.0) or 0.0),
        evidence=evidence if isinstance(evidence, dict) else {"note": str(evidence or "")},
        status=LifeEventStatus.DETECTED,
    )
    ctx.session.add(event)
    await ctx.session.flush()
    await ctx.audit_record(
        "engagement", "life_event.recorded", "life_event", str(event.id),
        {"type": etype, "confidence": event.confidence},
    )
    phrase = _LIFE_EVENT_PHRASE.get(etype, "something worth a look in your recent activity")
    await notify(
        ctx.session,
        ctx.customer_id,
        NotificationKind.LIFE_EVENT,
        "Sarathi noticed something",
        f"We spotted {phrase}. Tap to see how Sarathi can help.",
        link="/app/nudges",
    )
    append_structured(
        state, "life_events",
        {"id": str(event.id), "type": etype, "confidence": event.confidence},
    )
    return {"life_event_id": str(event.id), "type": etype, "status": "detected"}


async def _propose_outreach(ctx: AgentContext, state: AgentState, args: ToolArgs) -> ToolResult:
    if ctx.customer_id is None:
        return {"error": "no customer in context"}
    action = {
        "kind": normalize_action_kind(
            str(args.get("action_kind", "product_offer")), "product_offer"
        ),
        "product_code": args.get("product_code"),
        "life_event": args.get("life_event"),
    }
    proposal = await create_proposal(
        ctx.session,
        customer_id=ctx.customer_id,
        agent="engagement",
        kind=ProposalKind.PRODUCT_OFFER,
        title=str(args.get("title", "Next best action")),
        body=str(args.get("body", "")),
        action=action,
    )
    await ctx.audit_record(
        "engagement", "proposal.created", "proposal", str(proposal.id),
        {"kind": proposal.kind.value, "product": action.get("product_code")},
    )
    append_proposal(state, str(proposal.id))
    return {"proposal_id": str(proposal.id), "status": "pending_approval"}


async def _score_churn(ctx: AgentContext, state: AgentState, args: ToolArgs) -> ToolResult:
    if ctx.customer_id is None:
        return {"error": "no customer in context"}
    features = args.get("features")
    if not isinstance(features, dict):
        features = await _analyze_window(ctx, state, {"days": int(args.get("days", 90) or 90)})

    base = feature_churn_score(features)

    # LLM refinement (blended); falls back to the feature score on failure.
    final = base
    llm_score: float | None = None
    started = perf_counter()
    try:
        resp = await ctx.router.chat(
            tier="fast",
            messages=[ChatMessage(role="user", content=_features_json(features))],
            system=(
                "Estimate churn probability (0.0-1.0) for this bank customer from the JSON "
                'features. Respond with ONLY JSON: {"churn_probability": <float>}.'
            ),
            json_mode=True,
            temperature=0.0,
            purpose="engagement:score_churn",
        )
        parsed = orjson.loads(resp.text)
        llm_score = max(0.0, min(1.0, float(parsed.get("churn_probability", base))))
        final = round(0.6 * base + 0.4 * llm_score, 3)
        await ctx.tracer.step(
            node=NODE_NAME, kind=AgentStepKind.LLM, name="score_churn.llm",
            input={"base": base}, output={"llm_score": llm_score, "final": final},
            model=resp.model, tokens_in=resp.tokens_in, tokens_out=resp.tokens_out,
            cost_usd=resp.cost_usd, latency_ms=int((perf_counter() - started) * 1000),
        )
    except Exception:
        final = base

    customer = await ctx.session.get(Customer, ctx.customer_id)
    if customer is not None:
        customer.churn_risk = final
        await ctx.session.flush()
    await ctx.audit_record(
        "engagement", "churn.scored", "customer", str(ctx.customer_id),
        {"base": base, "llm": llm_score, "final": final},
    )
    return {"churn_risk": final, "feature_score": base, "llm_score": llm_score}


def feature_churn_score(features: dict[str, Any]) -> float:
    """Deterministic churn base score from extracted features (0..1)."""
    score = 0.0
    salary = features.get("salary") or {}
    if not salary.get("detected"):
        score += 0.3
    if salary.get("direction") == "down":
        score += 0.2
    trend = features.get("balance_trend") or {}
    if trend.get("direction") == "down":
        change = trend.get("change_paise", 0)
        start = trend.get("start_paise", 0) or 1
        if abs(change) > 0.5 * abs(start):
            score += 0.3
        else:
            score += 0.15
    if features.get("balance_drain_present"):
        score += 0.25
    if features.get("upi_txn_count", 0) == 0:
        score += 0.15
    return round(min(score, 1.0), 3)


def build_tools() -> dict[str, Tool]:
    tools = [
        make_tool(
            "analyze_window", "Extract deterministic behavioural features over a window.",
            obj_schema({"days": {"type": "integer"}}),
            _analyze_window,
        ),
        make_tool(
            "detect_life_events", "Detect life-event candidates from features (LLM, JSON).",
            obj_schema({"days": {"type": "integer"}, "features": {"type": "object"}}),
            _detect_life_events,
        ),
        make_tool(
            "record_life_event", "Persist a detected life event.",
            obj_schema({
                "type": {"type": "string", "enum": _LIFE_EVENT_VALUES},
                "confidence": {"type": "number"},
                "evidence": {"type": "object"},
            }, required=["type"]),
            _record_life_event,
        ),
        make_tool(
            "propose_outreach", "Propose a congratulatory NBA offer for human approval.",
            obj_schema({
                "title": {"type": "string"},
                "body": {"type": "string"},
                "product_code": {"type": "string"},
                "life_event": {"type": "string"},
            }, required=["title", "body"]),
            _propose_outreach,
        ),
        make_tool(
            "score_churn", "Compute and persist the customer's churn risk.",
            obj_schema({"days": {"type": "integer"}, "features": {"type": "object"}}),
            _score_churn,
        ),
    ]
    return {t.name: t for t in tools}


_TOOLS = build_tools()


async def engagement_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    return await run_specialist(
        state, config,
        agent_name=AGENT_NAME, node_name=NODE_NAME,
        system_builder=_system, tools=_TOOLS,
    )
