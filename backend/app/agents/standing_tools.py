"""Standing-instruction agent tools for the adoption specialist.

Two tools:

- ``list_standing_instructions`` (read, direct): shows the customer's recurring
  auto-transfers with live status.
- ``setup_standing_instruction`` (write, HITL): does NOT create the instruction
  directly. It resolves the customer's account/goal, then files a **proposal**
  (``kind=action``, ``action.kind="create_standing_instruction"``) into the human
  approval queue. The real row is created only when a staff member approves it
  (see :func:`app.agents.entrypoints._dispatch_create_standing`). This keeps an
  impactful, money-moving setup off the LLM's direct-write path.
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa

from app.agents.actions import create_proposal
from app.agents.context import AgentContext
from app.agents.state import AgentState, append_proposal
from app.agents.toolkit import Tool, ToolArgs, ToolResult, make_tool, obj_schema
from app.models.enums import AccountStatus, GoalStatus, ProposalKind, StandingPurpose
from app.models.goal import SavingsGoal
from app.services import ledger, standing


async def _list_standing_instructions(
    ctx: AgentContext, _state: AgentState, _args: ToolArgs
) -> ToolResult:
    if ctx.customer_id is None:
        return {"instructions": [], "note": "no account yet - open one to set up an auto-transfer"}
    views = await standing.list_for_customer(ctx.session, ctx.customer_id)
    active = await standing.count_active(ctx.session, ctx.customer_id)
    return {
        "instructions": [
            {
                "id": str(v.instruction.id),
                "purpose": v.instruction.purpose.value,
                "goal_name": v.goal_name,
                "amount_paise": v.instruction.amount_paise,
                "cadence": v.instruction.cadence.value,
                "next_run_date": v.instruction.next_run_date.isoformat(),
                "status": v.instruction.status.value,
                "runs_count": v.instruction.runs_count,
            }
            for v in views
        ],
        "active_count": active,
        "max_active": standing.MAX_ACTIVE,
    }


async def _resolve_account_id(ctx: AgentContext) -> uuid.UUID | None:
    """Pick the customer's source account: the first active one, else the first."""
    if ctx.customer_id is None:
        return None
    accounts = await ledger.list_accounts(ctx.session, ctx.customer_id)
    if not accounts:
        return None
    for account in accounts:
        if account.status is AccountStatus.ACTIVE:
            return account.id
    return accounts[0].id


async def _resolve_goal_id(
    ctx: AgentContext, args: ToolArgs
) -> tuple[uuid.UUID | None, str | None]:
    """Resolve a goal from an explicit id or a fuzzy name. Returns ``(id, error)``."""
    if ctx.customer_id is None:
        return None, "no account yet"
    raw_id = args.get("goal_id")
    if raw_id:
        try:
            gid = uuid.UUID(str(raw_id))
        except ValueError:
            return None, "invalid goal id"
        goal = await ctx.session.get(SavingsGoal, gid)
        if goal is None or goal.customer_id != ctx.customer_id:
            return None, "goal not found"
        if goal.status is not GoalStatus.ACTIVE:
            return None, "that goal is not active"
        return goal.id, None

    name = str(args.get("goal_name", "")).strip()
    if not name:
        return None, "which goal? give a goal name or id"
    match = await ctx.session.scalar(
        sa.select(SavingsGoal)
        .where(
            SavingsGoal.customer_id == ctx.customer_id,
            SavingsGoal.status == GoalStatus.ACTIVE,
            sa.func.lower(SavingsGoal.name).like(f"%{name.lower()}%"),
        )
        .order_by(SavingsGoal.created_at.desc())
    )
    if match is None:
        return None, f"no active goal matching '{name}'"
    return match.id, None


def build_standing_tools(agent_name: str) -> list[Tool]:
    """Return the standing-instruction tools, wiring ``agent_name`` into the audit trail."""

    async def _setup_standing_instruction(
        ctx: AgentContext, state: AgentState, args: ToolArgs
    ) -> ToolResult:
        if ctx.customer_id is None:
            return {"proposed": False, "error": "no account yet - open one first"}

        purpose_raw = str(args.get("purpose", "")).strip().lower()
        if purpose_raw not in {p.value for p in StandingPurpose}:
            return {"proposed": False, "error": "purpose must be goal, fd, or savings"}
        purpose = StandingPurpose(purpose_raw)

        cadence = str(args.get("cadence", "monthly")).strip().lower()
        if cadence not in {"weekly", "monthly"}:
            return {"proposed": False, "error": "cadence must be weekly or monthly"}

        if args.get("amount_paise") is not None:
            amount_paise = int(args.get("amount_paise") or 0)
        else:
            amount_paise = int(args.get("amount_rupees") or 0) * 100
        if amount_paise <= 0:
            return {"proposed": False, "error": "amount must be a positive number of rupees"}

        account_id = await _resolve_account_id(ctx)
        if account_id is None:
            return {"proposed": False, "error": "no account to draw from"}

        goal_id: uuid.UUID | None = None
        if purpose is StandingPurpose.GOAL:
            goal_id, err = await _resolve_goal_id(ctx, args)
            if err is not None:
                return {"proposed": False, "error": err}

        rupees = amount_paise // 100
        goal_suffix = ""
        if purpose is StandingPurpose.GOAL and goal_id is not None:
            goal = await ctx.session.get(SavingsGoal, goal_id)
            if goal is not None:
                goal_suffix = f" toward '{goal.name}'"
        purpose_word = {"goal": "your goal", "fd": "a fixed deposit", "savings": "savings"}[
            purpose.value
        ]
        title = f"Auto-transfer ₹{rupees:,} {cadence} to {purpose_word}"
        body = (
            f"Set up a {cadence} auto-transfer of ₹{rupees:,} into {purpose_word}{goal_suffix}. "
            "Runs only when the account keeps a ₹1,000 cushion; you can pause or cancel it anytime."
        )
        action: dict[str, Any] = {
            "kind": "create_standing_instruction",
            "from_account_id": str(account_id),
            "purpose": purpose.value,
            "goal_id": str(goal_id) if goal_id is not None else None,
            "amount_paise": amount_paise,
            "cadence": cadence,
        }
        proposal = await create_proposal(
            ctx.session,
            customer_id=ctx.customer_id,
            agent=agent_name,
            kind=ProposalKind.ACTION,
            title=title,
            body=body,
            action=action,
        )
        await ctx.audit_record(
            agent_name,
            "standing.proposed",
            "proposal",
            str(proposal.id),
            {"purpose": purpose.value, "amount_paise": amount_paise, "cadence": cadence},
        )
        append_proposal(state, str(proposal.id))
        return {"proposed": True, "proposal_id": str(proposal.id), "status": "pending_approval"}

    return [
        make_tool(
            "list_standing_instructions",
            "List the customer's recurring auto-transfers (standing instructions) with status.",
            obj_schema({}),
            _list_standing_instructions,
        ),
        make_tool(
            "setup_standing_instruction",
            "Propose a recurring auto-transfer for the customer. This does NOT create it "
            "directly - it files a proposal a human must approve. Amount in whole rupees.",
            obj_schema(
                {
                    "purpose": {
                        "type": "string",
                        "enum": ["goal", "fd", "savings"],
                        "description": "what the transfer feeds: a savings goal, an FD, or savings",
                    },
                    "amount_rupees": {"type": "integer", "description": "amount in rupees"},
                    "cadence": {"type": "string", "enum": ["weekly", "monthly"]},
                    "goal_name": {
                        "type": "string",
                        "description": "goal to save toward (required when purpose is goal)",
                    },
                    "goal_id": {"type": "string", "description": "optional exact goal id"},
                },
                required=["purpose", "amount_rupees", "cadence"],
            ),
            _setup_standing_instruction,
        ),
    ]
