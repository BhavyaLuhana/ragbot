"""
The Chunk domain primitive.

A Chunk is the atomic unit of the RAG system: a slice of source text
plus the metadata needed to cite it, filter it, and deduplicate it.
Written by ingestion, read by retrieval, referenced by citations.

Lives on its own (not inside ingest.py or retrieve.py) because putting it
anywhere else inverts the dependency direction — retrieval shouldn't have
to import from ingestion to describe the thing it returns.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ChunkMetadata(BaseModel):
    """
    Provenance + filterable attributes attached to every chunk (ADR-008).

    Kept as its own model (not flat fields on Chunk) so:
    - Chroma's `where` filter maps 1:1 to these keys — no translation layer.
    - Retrieval results can carry metadata without dragging the raw text
      into log lines or API responses.
    - Future metadata fields are additive, not breaking changes to Chunk.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str = Field(..., description="UUID4 assigned at ingest time.")
    source: str = Field(..., description="Original filename, e.g. 'TechCorp_..._Handbook.pdf'.")
    page: int = Field(..., ge=1, description="1-indexed page number in the source PDF.")
    section: str = Field(
        default="",
        description="Best-effort section heading; empty if none detected.",
    )
    chunk_index: int = Field(..., ge=0, description="Ordinal position within the document.")
    char_start: int = Field(..., ge=0, description="Character offset in concatenated doc text.")
    char_end: int = Field(..., ge=0, description="Character offset (exclusive) in concatenated doc text.")
    doc_hash: str = Field(
        ..., min_length=8, description="sha256 of the source PDF; used for dedup and re-ingest detection."
    )


class Chunk(BaseModel):
    """
    A retrievable unit: text + metadata.

    `text` is the exact string that was embedded and will be shown to the
    LLM. `metadata` carries everything needed to cite or filter the chunk.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1)
    metadata: ChunkMetadata


# ─────────────────────────────────────────────────────────────
# Retrieval-side view
# ─────────────────────────────────────────────────────────────
RetrieverName = Literal["dense", "sparse", "rrf", "rerank"]


class ScoredChunk(BaseModel):
    """
    A Chunk plus its retrieval score and which retriever produced it.

    Returned by dense.py / sparse.py / fusion.py / rerank.py. The final
    response exposes only the reranked ScoredChunks (with `retriever="rerank"`),
    but intermediate stages carry their own tag so eval scripts can inspect
    what each stage contributed.
    """

    model_config = ConfigDict(extra="forbid")

    chunk: Chunk
    score: float = Field(..., description="Stage-specific score; higher is better.")
    retriever: RetrieverName = Field(..., description="Which stage produced this row.")


__all__ = [
    "Chunk",
    "ChunkMetadata",
    "ScoredChunk",
    "RetrieverName",
]