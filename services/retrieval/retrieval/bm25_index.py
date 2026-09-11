"""
BM25 index loader + query wrapper.

Loads `bm25.pkl` and `docstore.json` from disk (written by the ingestion
service), exposes:
  - `load_index()` — reads both files into memory (called once at startup)
  - `BM25Index.search(query, top_k)` — returns ScoredChunk list
  - `BM25Index.get_chunk(chunk_id)` — rehydrate a single chunk

Design notes:
- Load once at FastAPI startup (lifespan), cache in app.state. The index
  is read-only at runtime; re-ingest requires a service restart (or the
  future /reload endpoint).
- The docstore is JSON keyed by chunk_id, so we can rebuild `Chunk`
  objects without touching Chroma.
- Tokenizer mirrors ingestion's `_tokenize` exactly. If they ever drift,
  BM25 scores silently change — so both sides use the same rule:
  lowercase + whitespace split, no stemming, no stopwords.
"""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from pathlib import Path

from rank_bm25 import BM25Okapi
from shared.config.settings import settings
from shared.logging.setup import get_logger
from shared.schemas.chunk import Chunk, ChunkMetadata, ScoredChunk

log = get_logger(__name__)


class IndexNotReadyError(RuntimeError):
    """Raised when BM25 or the docstore has not been ingested yet."""


def _tokenize(text: str) -> list[str]:
    """Must match ingestion.ingest._tokenize byte-for-byte in behaviour."""
    return text.lower().split()


@dataclass
class BM25Index:
    """In-memory BM25 + docstore, loaded once per process."""

    bm25: BM25Okapi
    docstore: dict[str, dict]  # chunk_id -> {text, metadata}
    ordered_chunk_ids: list[str]  # same order as the corpus BM25 was built on

    def search(self, query: str, top_k: int = 20) -> list[ScoredChunk]:
        """
        Score all docs against the query, return top_k as ScoredChunk.

        BM25Okapi.get_scores returns a numpy array parallel to
        `ordered_chunk_ids`. We don't filter zero-score rows — some
        queries legitimately match nothing, and the fusion layer handles
        empty lists fine.
        """
        if not query.strip():
            return []

        tokens = _tokenize(query)
        scores = self.bm25.get_scores(tokens)

        # Pair (index, score) and take the top-k by score.
        ranked = sorted(
            ((i, float(s)) for i, s in enumerate(scores)),
            key=lambda pair: pair[1],
            reverse=True,
        )[:top_k]

        out: list[ScoredChunk] = []
        for idx, score in ranked:
            chunk_id = self.ordered_chunk_ids[idx]
            entry = self.docstore.get(chunk_id)
            if entry is None:
                # Shouldn't happen if pickle+docstore are in sync, but
                # we'd rather skip a single bad row than blow up a query.
                log.warning("bm25_docstore_missing_row", chunk_id=chunk_id)
                continue
            out.append(
                ScoredChunk(
                    chunk=_entry_to_chunk(entry),
                    score=score,
                    retriever="sparse",
                )
            )
        return out

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        entry = self.docstore.get(chunk_id)
        return _entry_to_chunk(entry) if entry else None

    def __len__(self) -> int:
        return len(self.ordered_chunk_ids)


def _entry_to_chunk(entry: dict) -> Chunk:
    return Chunk(
        text=entry["text"],
        metadata=ChunkMetadata.model_validate(entry["metadata"]),
    )


def load_index(
    pickle_path: Path | None = None,
    docstore_path: Path | None = None,
) -> BM25Index:
    """
    Read bm25.pkl + docstore.json from disk.

    Raises:
        IndexNotReadyError: if either file is missing — means ingestion
            hasn't run yet, or the paths in settings are wrong.
    """
    pkl = pickle_path or settings.bm25_pickle
    ds = docstore_path or settings.bm25_docstore

    if not pkl.is_file():
        raise IndexNotReadyError(
            f"BM25 pickle not found at {pkl}. Run ingestion first."
        )
    if not ds.is_file():
        raise IndexNotReadyError(
            f"BM25 docstore not found at {ds}. Run ingestion first."
        )

    with pkl.open("rb") as f:
        bm25: BM25Okapi = pickle.load(f)

    with ds.open("r", encoding="utf-8") as f:
        docstore: dict[str, dict] = json.load(f)

    # `ordered_chunk_ids` must mirror the corpus order used to build BM25.
    # BM25Okapi doesn't store the input order, so we derive it from the
    # docstore's chunk_index values (which were written 0..N-1 by the
    # chunker, in document order).
    ordered = sorted(
        docstore.items(),
        key=lambda kv: int(kv[1]["metadata"]["chunk_index"]),
    )
    ordered_chunk_ids = [cid for cid, _ in ordered]

    if len(ordered_chunk_ids) != len(bm25.idf) if hasattr(bm25, "idf") else False:
        # Optional sanity check — BM25Okapi internals vary across versions,
        # so we don't hard-fail if `idf` isn't present.
        log.warning(
            "bm25_docstore_length_mismatch",
            bm25_rows=len(getattr(bm25, "idf", [])),
            docstore_rows=len(ordered_chunk_ids),
        )

    log.info(
        "bm25_index_loaded",
        chunks=len(ordered_chunk_ids),
        pickle=str(pkl),
        docstore=str(ds),
    )

    return BM25Index(
        bm25=bm25,
        docstore=docstore,
        ordered_chunk_ids=ordered_chunk_ids,
    )


__all__ = [
    "BM25Index",
    "IndexNotReadyError",
    "load_index",
]