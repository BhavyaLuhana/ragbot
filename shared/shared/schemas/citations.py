"""
Citation type — what the UI renders under each answer.

A Citation is a *presentation-shaped* view of a Chunk's metadata. We
deliberately keep it separate from ChunkMetadata so the API contract can
evolve (add a URL, a highlight range, a "confidence" label) without
touching the ingestion/retrieval internals.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Citation(BaseModel):
    """
    One source reference shown beneath an answer.

    Fields are chosen to be sufficient for the UI to render:
      "Handbook, p. 12 — 'Deployment Policy'"
    and to let a future "click to view source" feature scroll to the chunk.
    """

    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(..., description="Stable ID; matches Chunk.metadata.chunk_id.")
    source: str = Field(..., description="Filename of the source document.")
    page: int = Field(..., ge=1)
    section: str = Field(default="")
    score: float = Field(
        ...,
        description="Reranker score for this chunk. Higher = more relevant.",
    )
    snippet: str = Field(
        ...,
        max_length=300,
        description="Short excerpt of the chunk text for display; truncated for transport.",
    )

    @classmethod
    def from_chunk(cls, chunk, score: float, snippet_chars: int = 240) -> "Citation":
        """
        Build a Citation from a Chunk + score.

        `snippet` is a leading slice of the chunk text, not a mid-chunk
        window — we don't currently track offset alignment between the
        reranker's view and the original text, so leading slice is the
        honest, safe choice. `chunk_id` lets a future UI fetch the full
        text if needed.
        """
        text = chunk.text.strip().replace("\n", " ")
        snippet = text[:snippet_chars]
        if len(text) > snippet_chars:
            snippet = snippet.rstrip() + "…"
        return cls(
            chunk_id=chunk.metadata.chunk_id,
            source=chunk.metadata.source,
            page=chunk.metadata.page,
            section=chunk.metadata.section,
            score=score,
            snippet=snippet,
        )


__all__ = ["Citation"]