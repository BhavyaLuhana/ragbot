"""
Chat service API schemas.

The chat service owns conversation state. Retrieval is stateless; chat
holds session history, calls retrieval with recent turns for context,
streams the answer through, and appends the turn to the session.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.schemas.citations import Citation


Role = Literal["user", "assistant"]


class ChatMessage(BaseModel):
    """A single turn in a conversation."""

    model_config = ConfigDict(extra="forbid")

    role: Role
    content: str = Field(..., min_length=1)
    citations: list[Citation] = Field(
        default_factory=list,
        description="Empty for user messages; populated for assistant messages.",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ChatRequest(BaseModel):
    """POST /chat body (SSE streamed response)."""

    model_config = ConfigDict(extra="forbid")

    session_id: str | None = Field(
        default=None,
        description="If None, the server creates a new session and returns it via `session` event.",
    )
    message: str = Field(..., min_length=1, max_length=4000)
    metadata_filter: "MetadataFilter | None" = None  # type: ignore[name-defined]  # noqa: F821


class SessionResponse(BaseModel):
    """GET /sessions/{id} response."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    messages: list[ChatMessage]
    created_at: datetime
    updated_at: datetime


# ─────────────────────────────────────────────────────────────
# SSE events specific to chat
# ─────────────────────────────────────────────────────────────
ChatStreamEventType = Literal[
    "session",     # new session_id issued
    "token",       # a token from the answer
    "citations",   # citations for the completed answer
    "error",
    "done",
]


class SessionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["session"] = "session"
    session_id: str


class ChatTokenEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["token"] = "token"
    text: str


class ChatCitationsEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["citations"] = "citations"
    citations: list[Citation]


class ChatErrorEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["error"] = "error"
    message: str
    retryable: bool = False


class ChatDoneEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["done"] = "done"


# Late import to avoid circular dependency:
#   chat.py needs MetadataFilter, but retrieve.py imports chunk.py
#   which doesn't import chat.py — so the cycle is only chat ↔ retrieve.
# Resolving via model_rebuild() at the bottom keeps runtime happy.
from shared.schemas.retrieve import MetadataFilter  # noqa: E402

ChatRequest.model_rebuild()


__all__ = [
    "Role",
    "ChatMessage",
    "ChatRequest",
    "SessionResponse",
    "ChatStreamEventType",
    "SessionEvent",
    "ChatTokenEvent",
    "ChatCitationsEvent",
    "ChatErrorEvent",
    "ChatDoneEvent",
]