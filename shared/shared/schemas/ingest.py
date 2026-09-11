"""
Ingestion service API schemas.

The ingestion service is admin-triggered and idempotent per doc_hash:
re-POSTing the same PDF is a no-op unless `force=True`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class IngestRequest(BaseModel):
    """POST /ingest body."""

    model_config = ConfigDict(extra="forbid")

    pdf_path: str | None = Field(
        default=None,
        description="Absolute or repo-relative path to the PDF. "
        "If omitted, the service uses settings.source_pdf.",
    )
    force: bool = Field(
        default=False,
        description="If True, re-ingest even when doc_hash matches an existing index.",
    )


class IngestStats(BaseModel):
    """Counters returned from a successful ingest."""

    model_config = ConfigDict(extra="forbid")

    pages_loaded: int = Field(..., ge=0)
    chunks_created: int = Field(..., ge=0)
    chunks_embedded: int = Field(..., ge=0)
    chroma_upserts: int = Field(..., ge=0)
    bm25_indexed: int = Field(..., ge=0)
    duration_seconds: float = Field(..., ge=0.0)
    doc_hash: str = Field(..., min_length=8)


class IngestResponse(BaseModel):
    """POST /ingest response."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(..., description="'ingested' | 'skipped' — see ADR for idempotency.")
    collection: str = Field(..., description="Chroma collection name written to.")
    stats: IngestStats


class CollectionInfo(BaseModel):
    """GET /collections list entry."""

    model_config = ConfigDict(extra="forbid")

    name: str
    count: int = Field(..., ge=0)
    doc_hash: str | None = None


__all__ = [
    "IngestRequest",
    "IngestResponse",
    "IngestStats",
    "CollectionInfo",
]