"""
Dense retrieval — Chroma query wrapper.

Uses the same PersistentClient + collection as the ingestion service.
Retrieval is read-only: we never upsert from this service.

Design notes:
- The embedder is injected (retrieved once via the factory at startup).
  Dense search embeds the *query* (or the HyDE doc, when enabled) and
  asks Chroma for the nearest neighbours.
- We pass `include=["documents", "metadatas", "distances"]` and map
  Chroma's distance to a "higher is better" score. For cosine distance
  in [0, 2], score = 1 - distance/2 keeps the range sane for RRF (which
  ignores magnitude) and for the /retrieve/sync response.
- The sentinel row (chunk_index=-1) is filtered out via a Chroma
  `where` clause so it never appears in results.
"""

from __future__ import annotations

from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings
from shared.config.settings import settings
from shared.logging.setup import get_logger
from shared.providers.base import EmbeddingProvider
from shared.schemas.chunk import Chunk, ChunkMetadata, ScoredChunk

log = get_logger(__name__)


_SENTINEL_FILTER = {"chunk_index": {"$gte": 0}}


def get_chroma_client() -> chromadb.ClientAPI:
    """
    Mirror of ingestion.ingest.get_chroma_client — same path, same
    telemetry-off settings. Kept separate rather than imported across
    services so retrieval has zero import-time dependency on ingestion.
    """
    import logging as _logging
    _logging.getLogger("chromadb.telemetry.product.posthog").setLevel(_logging.CRITICAL)

    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=str(settings.chroma_dir),
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def get_collection(client: chromadb.ClientAPI) -> Any:
    """Fetch the configured collection. Raises if it doesn't exist."""
    return client.get_collection(settings.chroma_collection)


class DenseRetriever:
    """Thin wrapper around a Chroma collection + embedder."""

    def __init__(
        self,
        collection: Any,
        embedder: EmbeddingProvider,
        *,
        distance: str | None = None,
    ) -> None:
        self._collection = collection
        self._embedder = embedder
        self._distance = distance or settings.chroma_distance

    @property
    def collection(self) -> Any:
        return self._collection

    async def search(
        self,
        query: str,
        top_k: int = 20,
        where: dict[str, Any] | None = None,
    ) -> list[ScoredChunk]:
        """
        Embed `query`, ask Chroma for top_k nearest chunks, return
        ScoredChunk list sorted by score descending.

        `where` is an optional Chroma metadata filter; if provided, it is
        merged with the sentinel filter.
        """
        if not query.strip():
            return []

        query_vec = await self._embedder.embed_query(query)

        effective_where = _merge_where(where)

        result = self._collection.query(
            query_embeddings=[query_vec],
            n_results=top_k,
            where=effective_where,
            include=["documents", "metadatas", "distances"],
        )

        return _rows_to_scored(result, distance=self._distance)


def _merge_where(where: dict[str, Any] | None) -> dict[str, Any]:
    """Combine caller's filter with the sentinel exclusion."""
    if not where:
        return _SENTINEL_FILTER
    return {"$and": [_SENTINEL_FILTER, where]}


def _distance_to_score(distance: float, metric: str) -> float:
    """
    Normalize a Chroma distance into a "higher is better" score.

    - cosine: distance in [0, 2]; score = 1 - distance/2
    - l2:     distance >= 0; score = 1 / (1 + distance)
    - ip:     inner product is already a similarity; return as-is
    """
    if metric == "cosine":
        return 1.0 - (distance / 2.0)
    if metric == "ip":
        return distance
    return 1.0 / (1.0 + distance)


def _rows_to_scored(result: dict[str, Any], *, distance: str) -> list[ScoredChunk]:
    """
    Chroma returns nested lists (one per query embedding). We sent one
    query, so unpack index 0.
    """
    ids = (result.get("ids") or [[]])[0]
    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    dists = (result.get("distances") or [[]])[0]

    out: list[ScoredChunk] = []
    for cid, text, meta, dist in zip(ids, docs, metas, dists):
        if meta is None or text is None:
            continue
        try:
            chunk = Chunk(
                text=text,
                metadata=ChunkMetadata.model_validate(meta),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("dense_row_invalid", chunk_id=cid, error=str(exc))
            continue
        out.append(
            ScoredChunk(
                chunk=chunk,
                score=_distance_to_score(float(dist), distance),
                retriever="dense",
            )
        )
    return out


__all__ = [
    "DenseRetriever",
    "get_chroma_client",
    "get_collection",
]