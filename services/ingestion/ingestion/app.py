"""
FastAPI ingestion service.

Endpoints:
  POST /ingest        — run the full ingestion pipeline for a PDF
  GET  /health        — liveness + basic readiness signal
  GET  /collections   — list Chroma collections with row counts

Run locally:
  uvicorn ingestion.app:app --reload --port 8001

Design notes:
- The service is admin-triggered. No auth in v1 (documented non-goal).
- Ingestion runs in-process, awaited inside the request handler. For a
  7-page PDF this is ~5–40s. If the corpus grows we'd move to a queue
  (RabbitMQ) — see ADR-012.
- On startup we run `check_consistency()` and log the result; we do NOT
  hard-fail on inconsistency. Demo scope: warn loudly, keep serving.
- Errors map to explicit HTTP codes:
    LoaderError  → 400 (bad PDF path or unreadable file)
    ProviderError→ 502 (embedding provider down / not reachable)
    IngestError  → 500 (structural pipeline failure)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from shared.config.settings import settings
from shared.logging.setup import configure_logging, get_logger
from shared.providers.base import ProviderError
from shared.schemas.ingest import (
    CollectionInfo,
    IngestRequest,
    IngestResponse,
    IngestStats,
)

from ingestion.ingest import (
    IngestError,
    check_consistency,
    get_chroma_client,
    ingest_document,
)
from ingestion.loader import LoaderError


log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """
    Startup: configure logging, run consistency check, log readiness.
    Shutdown: nothing to tear down (PersistentClient flushes on GC).
    """
    configure_logging()

    log.info(
        "ingestion_service_starting",
        port=8001,
        collection=settings.chroma_collection,
        chroma_dir=str(settings.chroma_dir),
    )

    consistency = check_consistency()
    if consistency["ok"]:
        log.info("startup_consistency_ok", **consistency)
    else:
        log.warning(
            "startup_consistency_mismatch",
            **consistency,
            hint="POST /ingest with force=true to rebuild",
        )

    yield

    log.info("ingestion_service_stopping")


# ─────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────
app = FastAPI(
    title="RAG Ingestion Service",
    version="0.1.0",
    description="Loads, chunks, embeds, and stores source documents.",
    lifespan=lifespan,
)

# CORS (ADR-014). Ingestion is admin-triggered and normally called from
# CLI or curl, but we allow the frontend origin in case a future admin
# panel lives there.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────
@app.get("/health", tags=["meta"])
async def health() -> dict[str, object]:
    """Liveness + basic config echo. Never touches Chroma/BM25."""
    return {
        "status": "ok",
        "service": "ingestion",
        "collection": settings.chroma_collection,
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model,
        "embedding_dim": settings.embedding_dim,
    }


@app.get("/collections", response_model=list[CollectionInfo], tags=["meta"])
async def collections() -> list[CollectionInfo]:
    """
    List Chroma collections and their row counts.

    Chroma 0.5.x returned Collection objects from list_collections();
    0.6.x returns CollectionName (string-like). This handler treats the
    return value as a name and re-fetches via get_collection(), which
    works on both versions.

    Row count includes the sentinel row (chunk_index=-1) — subtracted
    when the sentinel is present so callers see the real chunk count.
    """
    try:
        client = get_chroma_client()
        # list_collections() -> CollectionName objects in 0.6.x,
        # Collection objects in 0.5.x. Treat as name strings in both.
        raw_items = client.list_collections()
        names: list[str] = [str(item) for item in raw_items]
    except Exception as exc:  # noqa: BLE001
        log.exception("collections_list_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list collections: {exc}",
        ) from exc

    out: list[CollectionInfo] = []
    for name in names:
        try:
            coll_obj = client.get_collection(name)
            raw_count = coll_obj.count()

            doc_hash: str | None = None
            real_count = raw_count
            try:
                got = coll_obj.get(
                    ids=["__ingest_sentinel__"],
                    include=["metadatas"],
                )
                metas = got.get("metadatas") or []
                if metas and metas[0] is not None:
                    doc_hash = metas[0].get("doc_hash")
                    real_count = raw_count - 1
            except Exception as inner_exc:  # noqa: BLE001
                log.warning(
                    "sentinel_read_failed",
                    collection=name,
                    error=str(inner_exc),
                )

            out.append(
                CollectionInfo(
                    name=name,
                    count=max(real_count, 0),
                    doc_hash=doc_hash,
                )
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("collection_inspect_failed", name=name, error=str(exc))
            out.append(
                CollectionInfo(
                    name=name,
                    count=0,
                    doc_hash=None,
                )
            )

    return out


@app.post("/ingest", response_model=IngestResponse, tags=["ingest"])
async def ingest(req: IngestRequest) -> IngestResponse:
    """
    Run the ingestion pipeline for a PDF.

    Body:
      - pdf_path: optional override (defaults to settings.source_pdf)
      - force:    re-ingest even when doc_hash matches

    Returns:
      IngestResponse with `status` = "ingested" | "skipped".
    """
    pdf_path = Path(req.pdf_path) if req.pdf_path else settings.source_pdf
    log.info(
        "ingest_requested",
        pdf=str(pdf_path),
        force=req.force,
    )

    try:
        result = await ingest_document(pdf_path=pdf_path, force=req.force)
    except LoaderError as exc:
        log.warning("ingest_loader_error", error=str(exc), pdf=str(pdf_path))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except ProviderError as exc:
        log.error(
            "ingest_provider_error",
            provider=exc.provider,
            error=str(exc),
            retryable=exc.retryable,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except IngestError as exc:
        log.error("ingest_structural_error", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # noqa: BLE001 — last resort
        log.exception("ingest_unexpected_error", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected ingestion failure: {exc}",
        ) from exc

    return IngestResponse(
        status=result.status,
        collection=result.collection,
        stats=IngestStats(
            pages_loaded=result.pages_loaded,
            chunks_created=result.chunks_created,
            chunks_embedded=result.chunks_embedded,
            chroma_upserts=result.chroma_upserts,
            bm25_indexed=result.bm25_indexed,
            duration_seconds=result.duration_seconds,
            doc_hash=result.doc_hash,
        ),
    )


__all__ = ["app"]