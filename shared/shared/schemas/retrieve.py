"""
Retrieval service API schemas.

The retrieval service is stateless per request: caller supplies a query
(and optionally recent chat history for context-aware rewriting), gets
back chunks + citations. It does not know about sessions — that's the
chat service's job.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.schemas.chunk import Chunk, ScoredChunk
from shared.schemas.citations import Citation


# ─────────────────────────────────────────────────────────────
# Request
# ─────────────────────────────────────────────────────────────
class MetadataFilter(BaseModel):
    """
    Optional Chroma `where` filter. Exposed as a typed model rather than a
    raw dict so callers can't accidentally send unsupported operators.
    Extend as needed (add `section_in`, date ranges, etc.).
    """

    model_config = ConfigDict(extra="forbid")

    source: str | None = Field(default=None, description="Exact filename match.")
    page_gte: int | None = Field(default=None, ge=1)
    page_lte: int | None = Field(default=None, ge=1)
    section_contains: str | None = Field(
        default=None,
        description="Case-insensitive substring match against ChunkMetadata.section.",
    )


class RetrieveRequest(BaseModel):
    """POST /retrieve and POST /retrieve/sync body."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int | None = Field(
        default=None, ge=1, le=50,
        description="Override settings.final_top_k. Reranked results returned.",
    )
    metadata_filter: MetadataFilter | None = None
    recent_turns: list[str] = Field(
        default_factory=list,
        max_length=6,
        description="Recent user queries for context-aware HyDE; oldest-first.",
    )


# ─────────────────────────────────────────────────────────────
# Response
# ─────────────────────────────────────────────────────────────
class StageTrace(BaseModel):
    """
    Per-stage candidate counts. Exposed in the response so evaluate.py and
    the UI's debug panel can see what each stage did. Cheap to compute.
    """

    model_config = ConfigDict(extra="forbid")

    dense_count: int = Field(..., ge=0)
    sparse_count: int = Field(..., ge=0)
    fused_count: int = Field(..., ge=0)
    reranked_count: int = Field(..., ge=0)
    hyde_used: bool


class RetrieveResponse(BaseModel):
    """Response for the non-streaming path (/retrieve/sync)."""

    model_config = ConfigDict(extra="forbid")

    query: str
    answer: str
    chunks: list[ScoredChunk] = Field(
        ...,
        description="Final reranked chunks, in order. `retriever='rerank'` on all entries.",
    )
    citations: list[Citation]
    trace: StageTrace


# ─────────────────────────────────────────────────────────────
# Streaming events (SSE payloads)
# ─────────────────────────────────────────────────────────────
# The SSE wire format emits one JSON object per `data:` line. The `type`
# field discriminates. This Literal is the single source of truth for
# which event kinds the frontend must handle.
StreamEventType = Literal["token", "citations", "trace", "error", "done"]


class SSEEvent(BaseModel):
    """
    Base shape of any SSE event. Concrete emissions are built with
    `.model_dump_json()` and framed as `data: {json}\n\n` by the SSE layer.

    Using one BaseModel subclass per event keeps the wire schema typed
    and documented; the frontend's JS consumer switches on `type`.
    """

    model_config = ConfigDict(extra="forbid")

    type: StreamEventType


class TokenEvent(SSEEvent):
    type: Literal["token"] = "token"
    text: str


class CitationsEvent(SSEEvent):
    type: Literal["citations"] = "citations"
    citations: list[Citation]


class TraceEvent(SSEEvent):
    type: Literal["trace"] = "trace"
    trace: StageTrace


class ErrorEvent(SSEEvent):
    type: Literal["error"] = "error"
    message: str
    retryable: bool = False


class DoneEvent(SSEEvent):
    type: Literal["done"] = "done"


__all__ = [
    "MetadataFilter",
    "RetrieveRequest",
    "StageTrace",
    "RetrieveResponse",
    "StreamEventType",
    "SSEEvent",
    "TokenEvent",
    "CitationsEvent",
    "TraceEvent",
    "ErrorEvent",
    "DoneEvent",
]