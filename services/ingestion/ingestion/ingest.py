"""
Ingestion orchestration: load → chunk → embed → store (Chroma + BM25).

This module ties together the loader, chunker, embedding provider, and
the two persistence backends. It exposes:
  - `ingest_document(...)`  — the full pipeline for one PDF
  - `check_consistency(...)` — startup sanity check between Chroma and
    the BM25 docstore
  - small helpers to open the Chroma collection and to load/save the
    BM25 index

Design notes:
- Ingestion is idempotent per doc_hash. Re-ingesting the same PDF is a
  no-op unless `force=True` (ADR on ingestion idempotency).
- We write to Chroma and BM25 independently, best-effort. If one
  succeeds and the other fails, we log loudly and leave the index in a
  partial state; `check_consistency()` will catch it on the next
  startup. Chosen for demo scope (ADR on consistency).
- Embeddings are batched by the provider (see providers/openai_provider
  and providers/ollama_provider). Ingestion just calls
  `provider.embed([...])` with the full list of chunk texts.
- The BM25 docstore is JSON, keyed by chunk_id, with full text and
  metadata. This lets retrieval rebuild `Chunk` objects without needing
  to hit Chroma for the text — a nice property if we ever want a
  Chroma-outage fallback.
"""

from __future__ import annotations

import json
import pickle
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import os

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY_IMPL", "chromadb.telemetry.product.posthog.Posthog")

import chromadb
from chromadb.config import Settings as ChromaSettings
from rank_bm25 import BM25Okapi
from shared.config.settings import settings
from shared.logging.setup import get_logger
from shared.providers.base import EmbeddingProvider, ProviderError
from shared.providers.factory import get_embedding_provider
from shared.schemas.chunk import Chunk

from ingestion.chunker import ChunkerConfig, chunk_document
from ingestion.loader import LoaderError, load_pdf

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────
# Result type
# ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class IngestResult:
    status: str  # "ingested" | "skipped"
    collection: str
    doc_hash: str
    pages_loaded: int
    chunks_created: int
    chunks_embedded: int
    chroma_upserts: int
    bm25_indexed: int
    duration_seconds: float


class IngestError(RuntimeError):
    """Raised when ingestion cannot complete for a structural reason."""


# ─────────────────────────────────────────────────────────────
# Chroma
# ─────────────────────────────────────────────────────────────
def get_chroma_client() -> chromadb.ClientAPI:
    """
    Embedded PersistentClient (ADR-001, decision 1A).

    `anonymized_telemetry=False` disables Chroma's PostHog ping — no
    reason to phone home for a local demo, and it removes a network
    dependency at startup.

    Note: Chroma 0.5.x has a known bug where a PostHog capture() call
    still fires with a stale signature, printing a "Failed to send
    telemetry event" line to stderr. The error is caught internally and
    is harmless; we silence its logger here to keep logs clean.
    """
    # Silence Chroma's telemetry logger — see docstring for rationale.
    import logging as _logging
    _logging.getLogger("chromadb.telemetry.product.posthog").setLevel(_logging.CRITICAL)

    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=str(settings.chroma_dir),
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def get_or_create_collection(client: chromadb.ClientAPI) -> Any:
    """
    Get the configured collection, creating it if missing.

    We supply `metadata={"hnsw:space": distance}` so Chroma knows the
    distance metric at creation time. Changing the metric later requires
    recreating the collection — which is why it lives in settings.
    """
    return client.get_or_create_collection(
        name=settings.chroma_collection,
        metadata={"hnsw:space": settings.chroma_distance},
    )


def _collection_doc_hash(client: chromadb.ClientAPI, collection_name: str) -> str | None:
    """
    Return the doc_hash of the currently-ingested document, or None if
    the collection is empty or missing.

    We store the doc_hash on a sentinel row so we can check idempotency
    without scanning all embeddings.
    """
    try:
        coll = client.get_collection(collection_name)
    except Exception:
        return None
    try:
        # Sentinel lives at chunk_index -1 with a magic chunk_id.
        got = coll.get(ids=[_SENTINEL_ID], include=["metadatas"])
        metadatas = got.get("metadatas") or []
        if metadatas:
            return metadatas[0].get("doc_hash")
    except Exception:
        return None
    return None


_SENTINEL_ID = "__ingest_sentinel__"


def _write_sentinel(
    coll: Any, *, doc_hash: str, source: str, chunk_count: int
) -> None:
    """
    Upsert a sentinel row carrying the doc_hash and chunk_count.

    Retrieval filters it out by `chunk_index >= 0`. Not elegant, but it
    keeps idempotency checks O(1) instead of requiring a metadata scan.
    """
    coll.upsert(
        ids=[_SENTINEL_ID],
        embeddings=[[0.0] * settings.embedding_dim],
        documents=[""],
        metadatas=[
            {
                "chunk_id": _SENTINEL_ID,
                "source": source,
                "page": 0,
                "section": "",
                "chunk_index": -1,
                "char_start": 0,
                "char_end": 0,
                "doc_hash": doc_hash,
                "chunk_count": chunk_count,
            }
        ],
    )


# ─────────────────────────────────────────────────────────────
# BM25 + docstore
# ─────────────────────────────────────────────────────────────
def _tokenize(text: str) -> list[str]:
    """
    Simple whitespace + lowercase tokenizer for BM25.

    We deliberately avoid a stemmer / stopword list:
    - The handbook uses many acronyms (SSO, RBAC, PII, SOC2) that a
      stemmer would mangle or strip as stopwords.
    - BM25's IDF term already downweights common words.
    - Fewer deps, easier to explain in the code walkthrough.
    """
    return text.lower().split()


def _save_bm25(
    chunks: list[Chunk], *, path_pkl: Path, path_docstore: Path
) -> int:
    """
    Build BM25Okapi over the chunk texts and persist:
      - path_pkl: pickled BM25Okapi (binary, not human-readable)
      - path_docstore: JSON, keyed by chunk_id, with text + metadata
    """
    path_pkl.parent.mkdir(parents=True, exist_ok=True)
    path_docstore.parent.mkdir(parents=True, exist_ok=True)

    corpus_tokens = [_tokenize(c.text) for c in chunks]
    bm25 = BM25Okapi(corpus_tokens)

    with path_pkl.open("wb") as f:
        pickle.dump(bm25, f, protocol=pickle.HIGHEST_PROTOCOL)

    docstore: dict[str, dict[str, Any]] = {}
    for c in chunks:
        docstore[c.metadata.chunk_id] = {
            "text": c.text,
            "metadata": c.metadata.model_dump(),
        }
    # Stable order + pretty print: nice diff-ability when debugging.
    with path_docstore.open("w", encoding="utf-8") as f:
        json.dump(docstore, f, indent=2, sort_keys=True, ensure_ascii=False)

    return len(chunks)


# ─────────────────────────────────────────────────────────────
# Consistency check
# ─────────────────────────────────────────────────────────────
def check_consistency() -> dict[str, Any]:
    """
    Startup sanity check between Chroma and the BM25 docstore.

    Returns a dict with counts + `ok` boolean. Called by app.py at
    startup; logs a warning if counts diverge.
    """
    result: dict[str, Any] = {
        "chroma_count": 0,
        "docstore_count": 0,
        "ok": True,
    }

    client = get_chroma_client()
    try:
        coll = client.get_collection(settings.chroma_collection)
        # Count excludes nothing — the sentinel has chunk_index=-1 and
        # will be subtracted below.
        result["chroma_count"] = coll.count()
    except Exception:
        result["chroma_count"] = 0

    if settings.bm25_docstore.is_file():
        try:
            with settings.bm25_docstore.open("r", encoding="utf-8") as f:
                docstore = json.load(f)
            result["docstore_count"] = len(docstore)
        except Exception as exc:
            log.warning("docstore_read_failed", error=str(exc))
            result["docstore_count"] = 0

    # Chroma count includes the sentinel (1 extra) when populated.
    # Treat "0 vs 0" (fresh install) and "N+1 vs N" (populated) as consistent.
    cc, dc = result["chroma_count"], result["docstore_count"]
    if cc == 0 and dc == 0:
        result["ok"] = True
    elif cc == dc + 1:
        result["ok"] = True
    else:
        result["ok"] = False

    if not result["ok"]:
        log.warning(
            "index_inconsistent",
            chroma_count=cc,
            docstore_count=dc,
            hint="re-run ingestion with force=True to rebuild both indexes",
        )
    return result


# ─────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────
async def ingest_document(
    pdf_path: Path | None = None,
    *,
    force: bool = False,
    embedder: EmbeddingProvider | None = None,
    chunker_config: ChunkerConfig | None = None,
) -> IngestResult:
    """
    Full pipeline: load → chunk → embed → Chroma upsert + BM25 save.

    Idempotent per doc_hash unless `force=True`.

    `embedder` is injectable for tests (pass a fake that returns
    deterministic vectors).

    Raises:
        LoaderError: PDF missing or unreadable.
        ProviderError: embedding provider failed.
        IngestError: post-load structural failure.
    """
    t0 = time.perf_counter()
    path = pdf_path or settings.source_pdf

    # ── 1. Load ─────────────────────────────────────────────
    doc = load_pdf(path)  # raises LoaderError
    log.info("ingest_load_ok", source=doc.source_name, pages=len(doc.pages))

    # ── 2. Idempotency check ────────────────────────────────
    client = get_chroma_client()
    existing_hash = _collection_doc_hash(client, settings.chroma_collection)

    if existing_hash == doc.doc_hash and not force:
        duration = time.perf_counter() - t0
        log.info(
            "ingest_skipped",
            reason="doc_hash_match",
            source=doc.source_name,
            doc_hash=doc.doc_hash[:12],
        )
        # Read chunk_count from sentinel for the response.
        coll = client.get_collection(settings.chroma_collection)
        got = coll.get(ids=[_SENTINEL_ID], include=["metadatas"])
        metas = got.get("metadatas") or []
        chunk_count = int(metas[0].get("chunk_count", 0)) if metas else 0
        return IngestResult(
            status="skipped",
            collection=settings.chroma_collection,
            doc_hash=doc.doc_hash,
            pages_loaded=len(doc.pages),
            chunks_created=chunk_count,
            chunks_embedded=0,
            chroma_upserts=0,
            bm25_indexed=0,
            duration_seconds=duration,
        )

    # ── 3. Chunk ────────────────────────────────────────────
    chunks = chunk_document(doc, chunker_config)
    if not chunks:
        raise IngestError(f"Chunker produced 0 chunks for {doc.source_name}")

    # ── 4. Embed ────────────────────────────────────────────
    provider = embedder or get_embedding_provider()
    texts = [c.text for c in chunks]
    try:
        vectors = await provider.embed(texts)
    except ProviderError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise IngestError(f"Embedding failed: {exc}") from exc

    if len(vectors) != len(chunks):
        raise IngestError(
            f"Embedding count mismatch: {len(vectors)} vectors for {len(chunks)} chunks"
        )

    # ── 5. Chroma upsert ────────────────────────────────────
    # If we're re-ingesting with force=True, wipe first so the index is
    # exactly the new document (no ghost chunks from a previous version).
    if force and existing_hash is not None:
        try:
            client.delete_collection(settings.chroma_collection)
            log.info("chroma_collection_deleted_for_force", collection=settings.chroma_collection)
        except Exception as exc:  # noqa: BLE001
            log.warning("chroma_delete_failed", error=str(exc))

    coll = get_or_create_collection(client)

    ids = [c.metadata.chunk_id for c in chunks]
    documents = [c.text for c in chunks]
    metadatas = [c.metadata.model_dump() for c in chunks]

    coll.upsert(
        ids=ids,
        embeddings=vectors,
        documents=documents,
        metadatas=metadatas,
    )
    _write_sentinel(
        coll,
        doc_hash=doc.doc_hash,
        source=doc.source_name,
        chunk_count=len(chunks),
    )
    log.info("chroma_upsert_ok", collection=settings.chroma_collection, count=len(chunks))

    # ── 6. BM25 + docstore ──────────────────────────────────
    bm25_indexed = _save_bm25(
        chunks,
        path_pkl=settings.bm25_pickle,
        path_docstore=settings.bm25_docstore,
    )
    log.info("bm25_saved", path=str(settings.bm25_pickle), count=bm25_indexed)

    duration = time.perf_counter() - t0
    log.info(
        "ingest_complete",
        source=doc.source_name,
        doc_hash=doc.doc_hash[:12],
        chunks=len(chunks),
        duration_s=round(duration, 2),
    )

    return IngestResult(
        status="ingested",
        collection=settings.chroma_collection,
        doc_hash=doc.doc_hash,
        pages_loaded=len(doc.pages),
        chunks_created=len(chunks),
        chunks_embedded=len(vectors),
        chroma_upserts=len(chunks) + 1,  # +sentinel
        bm25_indexed=bm25_indexed,
        duration_seconds=duration,
    )


__all__ = [
    "IngestError",
    "IngestResult",
    "check_consistency",
    "get_chroma_client",
    "get_or_create_collection",
    "ingest_document",
]