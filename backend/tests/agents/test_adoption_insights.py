"""Adoption's `get_spending_insights` tool: wired into the loop, real data out.

Scripts a FakeRouter tool call for `get_spending_insights` and drives it through
`adoption_node` (the real ReAct loop in `app.agents.toolkit.run_agent_loop`),
then asserts the tool actually executed against real transactions - not a
stub - by reading its traced step back from the database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from app.agents.adoption import _TOOLS, adoption_node
from app.agents.state import new_state
from app.llm.base import ToolCall
from app.models.banking import Account, Transaction
from app.models.customer import Customer
from app.models.enums import AccountStatus, AccountType, AgentStepKind, TxnChannel, TxnDirection
from app.models.tracing import AgentStep
from tests.agents.conftest import FakeRouter, ScriptedHandler, make_response


def test_get_spending_insights_is_registered() -> None:
    assert "get_spending_insights" in _TOOLS


async def _make_customer_with_spend(db) -> Customer:  # type: ignore[no-untyped-def]
    customer = Customer(full_name="Insights User")
    db.add(customer)
    await db.flush()
    account = Account(
        customer_id=customer.id, type=AccountType.SAVINGS,
        balance_paise=0, status=AccountStatus.ACTIVE,
    )
    db.add(account)
    await db.flush()

    now = datetime.now(UTC)
    db.add_all(
        [
            Transaction(
                account_id=account.id, ts=now, amount_paise=60_000_00,
                direction=TxnDirection.CREDIT, channel=TxnChannel.NEFT,
                category="salary", merchant="Acme Corp", balance_after_paise=60_000_00,
            ),
            Transaction(
                account_id=account.id, ts=now - timedelta(days=1), amount_paise=1_500_00,
                direction=TxnDirection.DEBIT, channel=TxnChannel.UPI,
                category="groceries", merchant="BigBasket", balance_after_paise=58_500_00,
            ),
        ]
    )
    await db.flush()
    await db.commit()
    return customer


async def test_adoption_tool_call_executes_against_real_transactions(  # type: ignore[no-untyped-def]
    make_ctx, db, sessionmaker_test
) -> None:
    customer = await _make_customer_with_spend(db)

    handler = ScriptedHandler(
        queues={
            "adoption:loop": [
                make_response(
                    "", tool_calls=[ToolCall(name="get_spending_insights", args={"months": 2})]
                ),
                make_response("Here's where your money went last month."),
            ],
        },
        default_text="fallback",
    )
    ctx = await make_ctx(FakeRouter(handler), customer_id=customer.id)
    state = new_state(
        conversation_id="c-insights", customer_id=str(customer.id),
        user_text="where did my money go last month?",
    )
    config = {"configurable": {"ctx": ctx}}

    out = await adoption_node(state, config)
    assert out["scratch"]["last_draft"] == "Here's where your money went last month."

    async with sessionmaker_test() as session:
        steps = list(
            (
                await session.scalars(
                    sa.select(AgentStep).where(AgentStep.run_id == ctx.tracer.run_id)
                )
            ).all()
        )

    tool_steps = [
        s for s in steps if s.kind == AgentStepKind.TOOL and s.name == "get_spending_insights"
    ]
    assert len(tool_steps) == 1
    result = tool_steps[0].output
    assert result is not None
    assert "error" not in result

    months = result["months"]
    assert len(months) == 2
    current = months[0]
    assert current["total_in_paise"] == 60_000_00
    assert current["by_category"][0]["category"] == "groceries"
    assert current["by_category"][0]["amount_paise"] == 1_500_00
    assert "trends" in result
    assert "recurring" in result["trends"]
