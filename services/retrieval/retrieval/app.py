"""
FastAPI retrieval service.

Endpoints:
  POST /retrieve          — streaming (SSE) answer + citations
  POST /retrieve/sync     — non-streaming, returns full JSON response
  GET  /health            — liveness + config echo
  POST /reload            — reload BM25 + Chroma (future work stub)

Startup (lifespan):
  - configure logging
  - load BM25 index + Chroma collection
  - warm-load the cross-encoder reranker
  - warm-up: run a single dummy query so Ollama's embedding model is
    hot before the first real user request (avoids the 30s cold-start
    hit we measured during ingestion)

Run locally:
  uvicorn retrieval.app:app --reload --port 8002
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from shared.config.settings import settings
from shared.logging.setup import configure_logging, get_logger
from shared.providers.base import ProviderError
from shared.providers.factory import get_embedding_provider, get_llm_provider
from shared.schemas.chunk import ScoredChunk, Chunk, ChunkMetadata
from shared.schemas.citations import Citation
from shared.schemas.retrieve import (
    MetadataFilter,
    RetrieveRequest,
    RetrieveResponse,
    StageTrace,
)

from retrieval.bm25_index import IndexNotReadyError, load_index
from retrieval.dense import DenseRetriever, get_chroma_client, get_collection
from retrieval.fusion import rrf_fuse
from retrieval.generate import stream_answer
from retrieval.hyde import generate_hyde
from retrieval.rerank import Reranker
from retrieval.sparse import SparseRetriever


log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    log.info("retrieval_service_starting", port=8002)

    # ── Load indexes ────────────────────────────────────────
    try:
        bm25 = load_index()
    except IndexNotReadyError as exc:
        log.error("startup_bm25_missing", error=str(exc))
        raise
    log.info("startup_bm25_ok", chunks=len(bm25))

    client = get_chroma_client()
    collection = get_collection(client)
    log.info("startup_chroma_ok", collection=collection.name, count=collection.count())

    # ── Providers ───────────────────────────────────────────
    embedder = get_embedding_provider()
    llm = get_llm_provider()
    log.info(
        "startup_providers_ok",
        embedder=embedder.model_name,
        llm=llm.model_name,
    )

    # ── Retriever wrappers ──────────────────────────────────
    dense = DenseRetriever(collection, embedder)
    sparse = SparseRetriever(bm25)

    # ── Reranker (warm) ─────────────────────────────────────
    reranker = Reranker()

    # ── Warm-up: one dummy embed + one dummy rerank ─────────
    # Ollama's first embedding call after idle is ~30s; doing it here
    # means the first user request is fast. Failures are non-fatal.
    try:
        await embedder.embed_query("warmup")
        log.info("startup_embedder_warmed")
    except Exception as exc:  # noqa: BLE001
        log.warning("startup_embedder_warmup_failed", error=str(exc))

    try:
        await reranker.rerank(
            "warmup",
            [
                ScoredChunk(
                    chunk=Chunk(
                        text="warmup",
                        metadata=ChunkMetadata(
                            chunk_id="warmup",
                            source="warmup",
                            page=1,
                            section="",
                            chunk_index=0,
                            char_start=0,
                            char_end=6,
                            doc_hash="0" * 64,
                        ),
                    ),
                    score=0.0,
                    retriever="dense",
                )
            ],
            top_k=1,
        )
        log.info("startup_reranker_warmed")
    except Exception as exc:  # noqa: BLE001
        log.warning("startup_reranker_warmup_failed", error=str(exc))

    # ── Stash on app.state for handlers ─────────────────────
    app.state.bm25 = bm25
    app.state.dense = dense
    app.state.sparse = sparse
    app.state.reranker = reranker
    app.state.llm = llm
    app.state.embedder = embedder

    log.info("retrieval_service_ready")

    yield

    log.info("retrieval_service_stopping")


# ─────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────
app = FastAPI(
    title="RAG Retrieval Service",
    version="0.1.0",
    description="Hybrid retrieval + rerank + streaming generation.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Type"],
)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def _metadata_filter_to_where(f: MetadataFilter | None) -> dict[str, Any] | None:
    """
    Translate the typed MetadataFilter into a Chroma `where` dict.

    Supported operators only — anything else is unsupported by design.
    """
    if f is None:
        return None

    clauses: list[dict[str, Any]] = []
    if f.source is not None:
        clauses.append({"source": {"$eq": f.source}})
    if f.page_gte is not None:
        clauses.append({"page": {"$gte": f.page_gte}})
    if f.page_lte is not None:
        clauses.append({"page": {"$lte": f.page_lte}})
    if f.section_contains is not None:
        # Chroma doesn't support substring on metadata — we filter
        # post-retrieval instead. But for parity we allow it via $eq on
        # full section match. Documented limitation.
        clauses.append({"section": {"$eq": f.section_contains}})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


async def _run_pipeline(
    req: RetrieveRequest,
    state: Any,
) -> tuple[list[ScoredChunk], StageTrace, str]:
    """
    Run the hybrid retrieval + rerank pipeline.

    Returns (final_chunks, trace, effective_dense_query).
    """
    dense: DenseRetriever = state.dense
    sparse: SparseRetriever = state.sparse
    reranker: Reranker = state.reranker
    llm = state.llm

    # ── HyDE (dense only) ───────────────────────────────────
    dense_query = req.query
    hyde_used = False
    if settings.hyde_enabled:
        dense_query, hyde_used = await generate_hyde(
            req.query,
            llm,
            recent_turns=req.recent_turns,
        )

    where = _metadata_filter_to_where(req.metadata_filter)

    # ── Dense + sparse in parallel ──────────────────────────
    import asyncio

    dense_task = asyncio.create_task(
        dense.search(dense_query, top_k=settings.dense_top_k, where=where)
    )
    # Sparse is CPU-bound sync — wrap in to_thread.
    sparse_task = asyncio.create_task(
        asyncio.to_thread(sparse.search, req.query, settings.sparse_top_k)
    )
    dense_results, sparse_results = await asyncio.gather(dense_task, sparse_task)

    # ── Fusion ──────────────────────────────────────────────
    fused = rrf_fuse(
        [dense_results, sparse_results],
        k=settings.rrf_k,
        top_k=settings.fusion_top_k,
    )

    # ── Rerank ──────────────────────────────────────────────
    final_k = req.top_k if req.top_k is not None else settings.final_top_k
    if settings.retrieval_rerank and fused:
        reranked = await reranker.rerank(req.query, fused, top_k=final_k)
    else:
        reranked = fused[:final_k]

    trace = StageTrace(
        dense_count=len(dense_results),
        sparse_count=len(sparse_results),
        fused_count=len(fused),
        reranked_count=len(reranked),
        hyde_used=hyde_used,
    )
    return reranked, trace, dense_query


# ─────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────
@app.get("/health", tags=["meta"])
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "service": "retrieval",
        "collection": settings.chroma_collection,
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "reranker_model": settings.reranker_model,
        "hyde_enabled": settings.hyde_enabled,
        "rerank_enabled": settings.retrieval_rerank,
    }


@app.post("/retrieve", tags=["retrieve"])
async def retrieve(req: RetrieveRequest, request: Request) -> StreamingResponse:
    """
    Streaming retrieval + generation. Returns text/event-stream of:
        token, citations, trace, done
    """
    chunks, trace, _ = await _run_pipeline(req, request.app.state)

    return StreamingResponse(
        stream_answer(req.query, chunks, request.app.state.llm, trace=trace),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/retrieve/sync", response_model=RetrieveResponse, tags=["retrieve"])
async def retrieve_sync(req: RetrieveRequest, request: Request) -> RetrieveResponse:
    """
    Non-streaming retrieval: returns chunks + a full answer string.

    Used by evaluate.py and by the /retrieve/sync debug panel.
    """
    chunks, trace, _ = await _run_pipeline(req, request.app.state)

    # Build the answer non-streamed.
    from retrieval.generate import build_prompt

    if not chunks:
        answer = "I couldn't find anything in the handbook that answers that question."
    else:
        prompt = build_prompt(req.query, chunks)
        try:
            answer = await request.app.state.llm.complete(prompt)
        except ProviderError as exc:
            log.error("retrieve_sync_llm_error", error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc

    citations = [Citation.from_chunk(c.chunk, score=c.score) for c in chunks]

    return RetrieveResponse(
        query=req.query,
        answer=answer,
        chunks=chunks,
        citations=citations,
        trace=trace,
    )


@app.post("/reload", status_code=status.HTTP_202_ACCEPTED, tags=["admin"])
async def reload_index(request: Request) -> dict[str, str]:
    """
    Reload the BM25 index + Chroma collection without a full restart.

    TODO: future work — currently a stub. The correct implementation
    is to re-run `load_index()` and re-fetch the Chroma collection, then
    swap them onto `app.state`. What's missing:
      - a lock so concurrent queries don't see a half-swapped state
      - draining in-flight requests before swap (or accept the race and
        document it)
      - a signal from the ingestion service (webhook or poll) that new
        data is ready, so callers don't have to know to hit /reload
    For demo scope, restart the service after ingestion.

    Reference: ADR-012 (REST over queue) — a message from ingestion
    would be the production-grade trigger for this.
    """
    log.info("reload_requested_but_stubbed")
    return {"status": "not_implemented", "note": "restart the service after ingestion"}


__all__ = ["app"]