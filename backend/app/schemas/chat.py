"""Pydantic v2 request/response schemas for the chat API (SSE)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatSessionCreateRequest(BaseModel):
    """Body for ``POST /chat/sessions``. Both fields optional (anonymous prospect chat)."""

    customer_id: uuid.UUID | None = None


class ChatSessionCreateResponse(BaseModel):
    conversation_id: str


class ChatMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


class ChatSessionUpdateRequest(BaseModel):
    """Body for ``PATCH /chat/sessions/{id}`` - rename a conversation.

    ``str_strip_whitespace`` trims first, so a whitespace-only title collapses to
    ``""`` and fails ``min_length=1`` (422) rather than persisting blank.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=100)


class ChatSessionRenameResponse(BaseModel):
    conversation_id: str
    title: str


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    role: str
    content: str
    created_at: datetime


class ChatSessionOut(BaseModel):
    conversation_id: str
    customer_id: uuid.UUID | None
    messages: list[MessageOut]


class ChatSessionSummary(BaseModel):
    conversation_id: str
    title: str
    message_count: int
    preview: str | None = None
    updated_at: datetime


class ChatSessionListResponse(BaseModel):
    sessions: list[ChatSessionSummary]


class ChatDoneEvent(BaseModel):
    """Shape of the terminal SSE ``done`` event's ``data`` payload (documentation only;
    the wire format is produced directly by ``app.agents.entrypoints.run_chat_turn``)."""

    run_id: str
    conversation_id: str
    customer_id: str | None
    intent: str | None
    agent: str | None
    final_text: str
    proposals: list[str]
    structured: dict[str, Any]
    trace: dict[str, Any]
