"""Public entry points for the agent mesh (consumed by Wave 3).

- :func:`run_chat_turn` — streaming chat turn; yields typed SSE events
  (``run_started`` → ``agent``/``tool_start``/``tool_end``/``token``/``structured``
  → ``done``), and creates the full ``agent_run``/``agent_step`` trace.
- :func:`run_event_trigger` — one non-streaming agent run for the Redis event
  consumer; returns an :class:`AgentRunResult`.
- :func:`execute_proposal` — human-in-the-loop executor: switches on the
  proposal's action kind (``send_nudge`` now; ``send_email`` delegated to the
  Wave 2B email service, imported lazily/duck-typed).
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from inspect import isawaitable
from typing import Any

from app.agents.actions import create_nudge
from app.agents.checkpointer import init_checkpointer
from app.agents.context import AgentContext, EventEmitter
from app.agents.graph import get_compiled_graph
from app.agents.guardrails import AuditTrail
from app.agents.state import turn_input
from app.agents.tracing import RunTracer
from app.core.db import get_sessionmaker
from app.core.logging import get_logger
from app.llm.embeddings import get_embedder
from app.llm.router import get_router
from app.models.conversation import Conversation, Message
from app.models.engagement import Proposal
from app.models.enums import (
    AgentRunStatus,
    AgentTriggerType,
    HoldingStatus,
    MessageRole,
    ProposalStatus,
)
from app.services import products

logger = get_logger(__name__)


def _uuid_or_none(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError):
        return None


async def init_agents() -> None:
    """Warm the checkpointer and compile the graph (call at app startup)."""
    await init_checkpointer()
    await get_compiled_graph()


# ===========================================================================
# Chat (streaming)
# ===========================================================================


async def run_chat_turn(
    conversation_id: str,
    customer_id: str | None,
    user_text: str,
) -> AsyncIterator[dict[str, Any]]:
    """Run one chat turn, yielding typed events for SSE."""
    sm = get_sessionmaker()
    cid = _uuid_or_none(customer_id)

    if cid is not None:
        await _persist_message(conversation_id, cid, MessageRole.USER, user_text)

    tracer = RunTracer(sm, agent="supervisor", trigger=AgentTriggerType.CHAT, customer_id=cid)
    await tracer.start()
    yield {"type": "run_started", "run_id": str(tracer.run_id), "conversation_id": conversation_id}

    emitter = EventEmitter()
    final_state: dict[str, Any] = {}
    error: str | None = None

    async with sm() as session:
        ctx = AgentContext(
            session=session,
            sessionmaker=sm,
            router=get_router(),
            embedder=get_embedder(),
            tracer=tracer,
            emitter=emitter,
            customer_id=cid,
            conversation_id=conversation_id,
        )
        state = turn_input(
            conversation_id=conversation_id,
            customer_id=customer_id,
            user_text=user_text,
            trigger="chat",
        )
        graph = await get_compiled_graph()
        config = {"configurable": {"ctx": ctx, "thread_id": conversation_id}}

        async def _drive() -> dict[str, Any]:
            try:
                out: dict[str, Any] = await graph.ainvoke(state, config=config)
                return out
            finally:
                await emitter.close()

        task = asyncio.create_task(_drive())
        async for event in emitter.stream():
            yield event

        try:
            final_state = await task
            await session.commit()
            await tracer.finish(AgentRunStatus.COMPLETED)
        except Exception as exc:
            await session.rollback()
            await tracer.finish(AgentRunStatus.FAILED)
            error = f"{type(exc).__name__}: {exc}"
            logger.warning("chat_turn_failed", error=error)

    if error is not None:
        yield {"type": "error", "message": error, "run_id": str(tracer.run_id)}
        return

    final_text = final_state.get("final_text", "")
    resolved_cid = _uuid_or_none(final_state.get("customer_id")) or cid
    if resolved_cid is not None and final_text:
        await _persist_message(conversation_id, resolved_cid, MessageRole.ASSISTANT, final_text)

    yield {
        "type": "done",
        "run_id": str(tracer.run_id),
        "conversation_id": conversation_id,
        "customer_id": str(resolved_cid) if resolved_cid else None,
        "intent": final_state.get("intent"),
        "agent": final_state.get("current_agent"),
        "final_text": final_text,
        "proposals": final_state.get("proposals_out", []),
        "structured": final_state.get("structured", {}),
        "trace": tracer.totals,
    }


async def _persist_message(
    conversation_id: str, customer_id: uuid.UUID, role: MessageRole, content: str
) -> None:
    conv_id = _uuid_or_none(conversation_id)
    if conv_id is None:
        return  # non-UUID thread id (e.g. prospect) — history lives in the checkpointer
    sm = get_sessionmaker()
    try:
        async with sm() as session:
            conv = await session.get(Conversation, conv_id)
            if conv is None:
                conv = Conversation(id=conv_id, customer_id=customer_id)
                session.add(conv)
                await session.flush()
            session.add(Message(conversation_id=conv_id, role=role, content=content))
            await session.commit()
    except Exception as exc:
        logger.warning("persist_message_failed", role=role.value, error=str(exc))


# ===========================================================================
# Event trigger (non-streaming)
# ===========================================================================


@dataclass(slots=True)
class AgentRunResult:
    run_id: str
    status: str
    final_text: str
    intent: str
    agent: str
    proposals: list[str] = field(default_factory=list)
    life_events: list[dict[str, Any]] = field(default_factory=list)
    nudges: list[str] = field(default_factory=list)
    structured: dict[str, Any] = field(default_factory=dict)
    trace: dict[str, Any] = field(default_factory=dict)


async def run_event_trigger(
    customer_id: str,
    event_summary: str,
    *,
    event: dict[str, Any] | None = None,
) -> AgentRunResult:
    """Run the agent mesh for a system event (Redis consumer path)."""
    sm = get_sessionmaker()
    cid = _uuid_or_none(customer_id)

    tracer = RunTracer(sm, agent="supervisor", trigger=AgentTriggerType.EVENT, customer_id=cid)
    await tracer.start()
    thread_id = f"event-{tracer.run_id}"
    payload = {"summary": event_summary, **(event or {})}

    status = AgentRunStatus.COMPLETED
    final_state: dict[str, Any] = {}
    async with sm() as session:
        ctx = AgentContext(
            session=session,
            sessionmaker=sm,
            router=get_router(),
            embedder=get_embedder(),
            tracer=tracer,
            emitter=None,
            customer_id=cid,
            conversation_id=thread_id,
        )
        state = turn_input(
            conversation_id=thread_id,
            customer_id=customer_id,
            user_text=event_summary,
            trigger="event",
            event=payload,
        )
        graph = await get_compiled_graph()
        config = {"configurable": {"ctx": ctx, "thread_id": thread_id}}
        try:
            final_state = await graph.ainvoke(state, config=config)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            status = AgentRunStatus.FAILED
            logger.warning("event_trigger_failed", error=str(exc))

    await tracer.finish(status)
    structured = final_state.get("structured", {})
    return AgentRunResult(
        run_id=str(tracer.run_id),
        status=status.value,
        final_text=final_state.get("final_text", ""),
        intent=final_state.get("intent", ""),
        agent=final_state.get("current_agent", ""),
        proposals=final_state.get("proposals_out", []),
        life_events=structured.get("life_events", []),
        nudges=structured.get("nudges", []),
        structured=structured,
        trace=tracer.totals,
    )


# ===========================================================================
# Proposal execution (HITL)
# ===========================================================================


@dataclass(slots=True)
class ProposalExecutionResult:
    proposal_id: str
    action_kind: str
    status: str
    detail: dict[str, Any] = field(default_factory=dict)


def _load_email_sender() -> Callable[..., Any] | None:
    """Lazily/duck-typed import of the Wave 2B email service (may not exist yet)."""
    try:
        from app.services import email as email_service
    except Exception:
        return None
    sender = getattr(email_service, "send_templated", None)
    return sender if callable(sender) else None


async def execute_proposal(proposal_id: str, approver: str) -> ProposalExecutionResult:
    """Approve and execute a pending proposal (impactful actions never auto-run)."""
    sm = get_sessionmaker()
    pid = _uuid_or_none(proposal_id)
    if pid is None:
        raise ValueError(f"invalid proposal id: {proposal_id!r}")

    async with sm() as session:
        proposal = await session.get(Proposal, pid)
        if proposal is None:
            raise ValueError(f"proposal {proposal_id} not found")
        if proposal.status not in (ProposalStatus.PENDING, ProposalStatus.APPROVED):
            raise ValueError(f"proposal already {proposal.status.value}")

        action = proposal.action or {}
        kind = str(action.get("kind", proposal.kind.value))
        detail = await _dispatch_action(session, proposal, action, kind)

        proposal.status = ProposalStatus.EXECUTED
        proposal.decided_by = approver
        proposal.decided_at = datetime.now(UTC)
        await AuditTrail().record(
            session, approver, "proposal.executed", "proposal", str(proposal.id),
            {"kind": kind, **detail},
        )
        await session.commit()
        return ProposalExecutionResult(
            proposal_id=str(proposal.id), action_kind=kind, status="executed", detail=detail
        )


async def _dispatch_action(
    session: Any, proposal: Proposal, action: dict[str, Any], kind: str
) -> dict[str, Any]:
    if kind in ("send_nudge", "nudge"):
        nudge = await create_nudge(
            session, customer_id=proposal.customer_id,
            title=proposal.title, body=proposal.body,
            cta=action.get("cta") if isinstance(action.get("cta"), dict) else {},
            proposal_id=proposal.id,
        )
        return {"nudge_id": str(nudge.id), "channel": "in_app"}

    if kind in ("product_offer", "offer"):
        code = action.get("product_code")
        if code:
            with contextlib.suppress(ValueError):
                await products.activate_holding(
                    session, customer_id=proposal.customer_id,
                    product_code=str(code), status=HoldingStatus.OFFERED,
                )
        nudge = await create_nudge(
            session, customer_id=proposal.customer_id,
            title=proposal.title, body=proposal.body,
            cta={"product_code": code} if code else {}, proposal_id=proposal.id,
        )
        return {"nudge_id": str(nudge.id), "product_code": code}

    if kind in ("send_email", "email"):
        sender = _load_email_sender()
        if sender is None:
            raise NotImplementedError(
                "email service 'app.services.email.send_templated' is not available yet "
                "(owned by Wave 2B); cannot execute send_email proposal"
            )
        return await _dispatch_email(sender, proposal, action)

    raise NotImplementedError(f"no executor for proposal action kind '{kind}'")


async def _dispatch_email(
    sender: Callable[..., Any], proposal: Proposal, action: dict[str, Any]
) -> dict[str, Any]:
    """Call the Wave 2B email service, duck-typed.

    Aligns to ``send_templated(to, template_name, context)`` but accepts an explicit
    ``action["email"]`` kwargs dict override for forward-compatibility.
    """
    supplied = action.get("email")
    if isinstance(supplied, dict):
        email_kwargs: dict[str, Any] = supplied
    else:
        email_kwargs = {
            "to": action.get("to"),
            "template_name": action.get("template_name") or action.get("template"),
            "context": action.get("context", {"title": proposal.title, "body": proposal.body}),
        }
    result = sender(**email_kwargs)
    if isawaitable(result):
        result = await result
    return {"email": "sent", "to": email_kwargs.get("to")}
