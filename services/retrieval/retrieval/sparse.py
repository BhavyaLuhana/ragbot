"""
Sparse retrieval — thin wrapper around BM25Index.

Separate module so `fusion.py` and `app.py` don't need to know whether
sparse search is BM25, TF-IDF, or something else. If we swap BM25 for
Splade later, only this file changes.
"""

from __future__ import annotations

from shared.schemas.chunk import ScoredChunk

from retrieval.bm25_index import BM25Index


class SparseRetriever:
    """Wraps a BM25Index behind a retrieve-shaped API."""

    def __init__(self, index: BM25Index) -> None:
        self._index = index

    def search(self, query: str, top_k: int = 20) -> list[ScoredChunk]:
        return self._index.search(query, top_k=top_k)

    def get_chunk(self, chunk_id: str):
        return self._index.get_chunk(chunk_id)

    def __len__(self) -> int:
        return len(self._index)


__all__ = ["SparseRetriever"]