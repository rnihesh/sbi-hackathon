"""Savings-goals agent tools, shared by the acquisition and adoption specialists.

Both specialists gain a read tool (``get_savings_goals``) and a write tool
(``create_savings_goal``) so a customer can review progress or set up a goal
conversationally ("help me save 50k by December" -> a real goal row). The write
tool reuses :func:`app.services.goals.create_goal`, so the active-goal cap and
input validation are identical to the REST surface - no divergent logic.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.agents.context import AgentContext
from app.agents.state import AgentState
from app.agents.toolkit import Tool, ToolArgs, ToolResult, make_tool, obj_schema
from app.services import goals


def _parse_target_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


async def _get_savings_goals(ctx: AgentContext, _state: AgentState, _args: ToolArgs) -> ToolResult:
    if ctx.customer_id is None:
        return {"goals": [], "note": "no account yet - open one to set a savings goal"}
    progresses = await goals.list_goals_with_progress(ctx.session, ctx.customer_id)
    return {
        "goals": [
            {
                "id": str(p.goal.id),
                "name": p.goal.name,
                "target_paise": p.goal.target_paise,
                "progress_paise": p.progress_paise,
                "pct": p.pct,
                "status": p.goal.status.value,
                "target_date": p.goal.target_date.isoformat() if p.goal.target_date else None,
            }
            for p in progresses
        ],
        "active_count": sum(1 for p in progresses if p.goal.status.value == "active"),
        "max_active": goals.MAX_ACTIVE_GOALS,
    }


def build_goal_tools(agent_name: str) -> list[Tool]:
    """Return the two goal tools, wiring ``agent_name`` into the audit trail."""

    async def _create_savings_goal(
        ctx: AgentContext, _state: AgentState, args: ToolArgs
    ) -> ToolResult:
        if ctx.customer_id is None:
            return {
                "created": False,
                "error": "no account yet - open an account first to set a savings goal",
            }
        name = str(args.get("name", "")).strip()
        if args.get("target_paise") is not None:
            target_paise = int(args.get("target_paise") or 0)
        else:
            target_paise = int(args.get("target_rupees") or 0) * 100
        target_date = _parse_target_date(args.get("target_date"))
        try:
            goal = await goals.create_goal(
                ctx.session,
                customer_id=ctx.customer_id,
                name=name,
                target_paise=target_paise,
                target_date=target_date,
            )
        except goals.GoalLimitError as exc:
            return {"created": False, "error": str(exc)}
        except goals.GoalError as exc:
            return {"created": False, "error": str(exc)}
        await ctx.audit_record(
            agent_name,
            "goal.created",
            "savings_goal",
            str(goal.id),
            {"name": goal.name, "target_paise": goal.target_paise},
        )
        return {
            "created": True,
            "goal_id": str(goal.id),
            "name": goal.name,
            "target_paise": goal.target_paise,
            "target_date": goal.target_date.isoformat() if goal.target_date else None,
        }

    return [
        make_tool(
            "get_savings_goals",
            "List the customer's savings goals with live progress toward each target.",
            obj_schema({}),
            _get_savings_goals,
        ),
        make_tool(
            "create_savings_goal",
            "Set up a savings goal for the customer (amount in whole rupees).",
            obj_schema(
                {
                    "name": {"type": "string", "description": "what they are saving for"},
                    "target_rupees": {"type": "integer", "description": "target amount in rupees"},
                    "target_date": {
                        "type": "string",
                        "description": "optional target date, ISO YYYY-MM-DD",
                    },
                },
                required=["name", "target_rupees"],
            ),
            _create_savings_goal,
        ),
    ]
