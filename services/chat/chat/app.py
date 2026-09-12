"""
FastAPI chat service.

Endpoints:
  POST /chat                 — SSE-streamed reply for a user turn
  GET  /sessions/{id}        — full transcript for a session
  DELETE /sessions/{id}      — drop a session
  GET  /health               — liveness + stats

Run locally:
  uvicorn chat.app:app --reload --port 8003
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from shared.config.settings import settings
from shared.logging.setup import configure_logging, get_logger
from shared.schemas.chat import ChatRequest, SessionResponse

from chat.orchestrator import stream_chat
from chat.session import SessionStore


log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    app.state.sessions = SessionStore()
    log.info(
        "chat_service_starting",
        port=8003,
        retrieval_url=settings.retrieval_url,
        session_ttl=settings.session_ttl_seconds,
    )
    yield
    log.info("chat_service_stopping")


app = FastAPI(
    title="RAG Chat Service",
    version="0.1.0",
    description="Session state + orchestration over the retrieval service.",
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
# Endpoints
# ─────────────────────────────────────────────────────────────
@app.get("/health", tags=["meta"])
async def health(request: Request) -> dict[str, object]:
    store: SessionStore = request.app.state.sessions
    return {
        "status": "ok",
        "service": "chat",
        "retrieval_url": settings.retrieval_url,
        "session_stats": store.stats(),
    }


@app.post("/chat", tags=["chat"])
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    """
    Send one user message; stream back SSE events:
      session   → {"session_id": "..."}           (first event)
      token     → {"text": "..."}                 (many)
      citations → {"citations": [...]}            (once, after tokens)
      trace     → {...}                           (optional passthrough)
      error     → {"message": "...", ...}         (on failure)
      done      → {}                              (last event)
    """
    store: SessionStore = request.app.state.sessions

    md_filter = None
    if req.metadata_filter is not None:
        md_filter = req.metadata_filter.model_dump(exclude_none=True)

    return StreamingResponse(
        stream_chat(
            user_message=req.message,
            session_id=req.session_id,
            store=store,
            metadata_filter=md_filter,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get(
    "/sessions/{session_id}",
    response_model=SessionResponse,
    tags=["chat"],
)
async def get_session(session_id: str, request: Request) -> SessionResponse:
    store: SessionStore = request.app.state.sessions
    session = store.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id!r} not found or expired",
        )
    from datetime import datetime
    return SessionResponse(
        session_id=session.session_id,
        messages=session.messages,
        created_at=datetime.utcfromtimestamp(session.created_at),
        updated_at=datetime.utcfromtimestamp(session.updated_at),
    )


@app.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["chat"],
)
async def delete_session(session_id: str, request: Request) -> None:
    store: SessionStore = request.app.state.sessions
    if not store.delete(session_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id!r} not found",
        )


__all__ = ["app"]