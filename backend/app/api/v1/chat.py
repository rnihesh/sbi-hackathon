"""Chat API: session bootstrap, SSE streaming turns, and transcript readback.

Cookie auth is optional here - prospects chat anonymously until (and unless) the
acquisition agent opens an account for them mid-conversation, at which point
``run_chat_turn`` starts returning a ``customer_id`` and message persistence
kicks in (see ``app.agents.entrypoints._persist_message``).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Annotated, Any, cast

import orjson
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.agents.entrypoints import run_chat_turn
from app.core.db import get_db
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.core.security import get_optional_user
from app.models.conversation import Conversation, Message
from app.models.customer import Customer
from app.models.enums import ConversationChannel
from app.models.identity import User
from app.schemas.chat import (
    ChatMessageRequest,
    ChatSessionCreateRequest,
    ChatSessionCreateResponse,
    ChatSessionListResponse,
    ChatSessionOut,
    ChatSessionSummary,
    MessageOut,
)
from app.workers.activity import publish_run_result

logger = get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

_background_drains: set[asyncio.Task[None]] = set()
"""Keeps a strong reference to fire-and-forget disconnect-drain tasks so they are
not garbage-collected mid-flight (see :func:`_drain_silently`)."""


def _uuid_or_none(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError):
        return None


async def _customer_for_user(db: AsyncSession, user: User | None) -> Customer | None:
    if user is None:
        return None
    result = await db.execute(select(Customer).where(Customer.user_id == user.id))
    return result.scalar_one_or_none()


@router.post("/sessions", response_model=ChatSessionCreateResponse)
async def create_chat_session(
    payload: ChatSessionCreateRequest | None = None,
    user: Annotated[User | None, Depends(get_optional_user)] = None,
    db: AsyncSession = Depends(get_db),
) -> ChatSessionCreateResponse:
    """Start a new conversation thread.

    ``customer_id`` in the body is accepted for forward-compatibility but is
    never trusted blindly - an authenticated caller is always bound to *their
    own* customer record (looked up from the session cookie), never an
    arbitrary id an anonymous caller could supply. Anonymous callers get a
    customer-less (prospect) thread; the acquisition agent may bind one mid-chat.
    """
    del payload  # accepted for schema/back-compat only; see docstring
    conversation_id = uuid.uuid4()
    customer = await _customer_for_user(db, user)

    if customer is not None:
        conv = Conversation(
            id=conversation_id, customer_id=customer.id, channel=ConversationChannel.APP
        )
        db.add(conv)
        await db.flush()

    return ChatSessionCreateResponse(conversation_id=str(conversation_id))


async def _authorize_conversation(
    conv: Conversation, user: User | None, db: AsyncSession
) -> None:
    customer = await _customer_for_user(db, user)
    if customer is None or customer.id != conv.customer_id:
        raise HTTPException(status_code=403, detail="Not your conversation")


async def _resolve_customer_id(
    db: AsyncSession, conversation_id: str, user: User | None
) -> tuple[uuid.UUID | None, Conversation | None]:
    """Resolve (and lazily bind) the customer that owns ``conversation_id``.

    Mirrors ``POST /chat/sessions``'s auto-bind rule so a message sent to a
    conversation id the client minted itself (skipping the create-session call)
    behaves identically. Raises ``403`` if an existing conversation belongs to
    someone else.
    """
    conv_uuid = _uuid_or_none(conversation_id)
    conv: Conversation | None = None
    if conv_uuid is not None:
        conv = await db.get(Conversation, conv_uuid)

    if conv is not None:
        await _authorize_conversation(conv, user, db)
        return conv.customer_id, conv

    customer = await _customer_for_user(db, user)
    if customer is None:
        return None, None

    if conv_uuid is not None:
        conv = Conversation(id=conv_uuid, customer_id=customer.id, channel=ConversationChannel.APP)
        db.add(conv)
        await db.flush()
    return customer.id, conv


def _sse_payload(event: dict[str, Any]) -> dict[str, str]:
    return {"event": str(event.get("type", "message")), "data": orjson.dumps(event).decode()}


async def _drain_silently(agen: AsyncIterator[dict[str, Any]]) -> None:
    """Let an abandoned (client-disconnected) run finish in the background.

    ``run_chat_turn`` already persists its own messages/trace/proposals
    transactionally; tearing it down mid-flight via ``aclose()`` would raise
    ``GeneratorExit`` at an arbitrary yield point inside that (Wave-2A-owned,
    not-to-be-modified) generator and could skip its final commit. Draining it
    to completion off to the side preserves that guarantee without keeping the
    now-closed HTTP response open.
    """
    try:
        async for _event in agen:
            pass
    except Exception:
        logger.warning("chat_background_drain_failed", exc_info=True)


async def _publish_chat_activity(customer_id: str | None, done_event: dict[str, Any]) -> None:
    if customer_id is None:
        return
    structured = done_event.get("structured") or {}
    await publish_run_result(
        get_redis(),
        customer_id=customer_id,
        run_id=str(done_event.get("run_id", "")),
        run_summary=(done_event.get("final_text") or "")[:200] or "Chat turn completed",
        proposals=list(done_event.get("proposals") or []),
        life_events=list(structured.get("life_events") or []),
        nudges=list(structured.get("nudges") or []),
    )


@router.post("/sessions/{conversation_id}/messages")
async def post_chat_message(
    conversation_id: str,
    payload: ChatMessageRequest,
    request: Request,
    user: Annotated[User | None, Depends(get_optional_user)] = None,
    db: AsyncSession = Depends(get_db),
) -> EventSourceResponse:
    """Stream one chat turn as SSE. Each Wave-2A event becomes ``event: <type>``."""
    customer_id, _conv = await _resolve_customer_id(db, conversation_id, user)
    await db.commit()
    customer_id_str = str(customer_id) if customer_id is not None else None

    async def event_source() -> AsyncIterator[dict[str, str]]:
        # `run_chat_turn` is declared `-> AsyncIterator[...]` but is actually an
        # async generator (we rely on `.aclose()` below, which `AsyncIterator`
        # doesn't guarantee but `AsyncGenerator` does).
        agen = cast(
            "AsyncGenerator[dict[str, Any], None]",
            run_chat_turn(conversation_id, customer_id_str, payload.text),
        )
        disconnected = False
        try:
            async for event in agen:
                yield _sse_payload(event)
                if event.get("type") == "done":
                    resolved_cid = event.get("customer_id") or customer_id_str
                    await _publish_chat_activity(resolved_cid, event)
                if await request.is_disconnected():
                    disconnected = True
                    logger.info("chat_sse_client_disconnected", conversation_id=conversation_id)
                    break
        finally:
            if disconnected:
                task = asyncio.ensure_future(_drain_silently(agen))
                _background_drains.add(task)
                task.add_done_callback(_background_drains.discard)
            else:
                await agen.aclose()

    return EventSourceResponse(event_source(), ping=15)


@router.get("/sessions", response_model=ChatSessionListResponse)
async def list_chat_sessions(
    user: Annotated[User | None, Depends(get_optional_user)] = None,
    db: AsyncSession = Depends(get_db),
) -> ChatSessionListResponse:
    """List the authed customer's conversations, newest first.

    Anonymous callers get an empty list (their thread lives only client-side).
    Title falls back to the first user message, truncated.
    """
    customer = await _customer_for_user(db, user)
    if customer is None:
        return ChatSessionListResponse(sessions=[])

    result = await db.execute(
        select(Conversation)
        .where(Conversation.customer_id == customer.id)
        .order_by(Conversation.created_at.desc())
        .limit(50)
    )
    conversations = result.scalars().all()
    if not conversations:
        return ChatSessionListResponse(sessions=[])

    conv_ids = [c.id for c in conversations]
    msg_rows = (
        await db.execute(
            select(Message.conversation_id, Message.role, Message.content, Message.created_at)
            .where(Message.conversation_id.in_(conv_ids))
            .order_by(Message.conversation_id, Message.created_at)
        )
    ).all()

    first_user_msg: dict[uuid.UUID, str] = {}
    counts: dict[uuid.UUID, int] = {}
    last_at: dict[uuid.UUID, Any] = {}
    for conv_id, role, content, created_at in msg_rows:
        counts[conv_id] = counts.get(conv_id, 0) + 1
        last_at[conv_id] = created_at
        if role == "user" and conv_id not in first_user_msg:
            first_user_msg[conv_id] = content

    sessions = []
    for conv in conversations:
        count = counts.get(conv.id, 0)
        if count == 0:
            continue  # empty threads (created but never used) add noise
        raw_title = conv.title or first_user_msg.get(conv.id, "New conversation")
        title = raw_title[:60] + ("…" if len(raw_title) > 60 else "")
        sessions.append(
            ChatSessionSummary(
                conversation_id=str(conv.id),
                title=title,
                message_count=count,
                updated_at=last_at.get(conv.id, conv.created_at),
            )
        )
    sessions.sort(key=lambda s: s.updated_at, reverse=True)
    return ChatSessionListResponse(sessions=sessions)


@router.get("/sessions/{conversation_id}", response_model=ChatSessionOut)
async def get_chat_session(
    conversation_id: str,
    user: Annotated[User | None, Depends(get_optional_user)] = None,
    db: AsyncSession = Depends(get_db),
) -> ChatSessionOut:
    conv_uuid = _uuid_or_none(conversation_id)
    if conv_uuid is None:
        return ChatSessionOut(conversation_id=conversation_id, customer_id=None, messages=[])

    conv = await db.get(Conversation, conv_uuid)
    if conv is None:
        return ChatSessionOut(conversation_id=conversation_id, customer_id=None, messages=[])

    await _authorize_conversation(conv, user, db)
    result = await db.execute(
        select(Message).where(Message.conversation_id == conv_uuid).order_by(Message.created_at)
    )
    messages = result.scalars().all()
    return ChatSessionOut(
        conversation_id=conversation_id,
        customer_id=conv.customer_id,
        messages=[MessageOut.model_validate(m) for m in messages],
    )
