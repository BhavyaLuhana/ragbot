"""
Chat orchestration.

Glues session state, the retrieval service, and SSE framing together.

For a given (session_id, user_message):
  1. Load or create the session.
  2. Append the user message to session history.
  3. Emit a `session` event (so a new client learns its session_id).
  4. Call the retrieval service's /retrieve SSE endpoint, forwarding
     recent turns for context-aware HyDE.
  5. Relay the retrieval SSE stream verbatim to the client — except we
     also capture the assistant tokens to append to session history.
  6. Append the assistant reply (with citations) to the session.
  7. Emit `done`.

Design notes:
- Chat is a *relay* + *state*. All the RAG work is done by retrieval.
  This keeps the chat service dependency-free (no torch, no chromadb).
- We re-frame the SSE: retrieval emits `event: token` etc.; we emit the
  same but prefix each stream with a `session` event. The `session`
  event tells a first-time client its id — the alternative is a
  separate handshake endpoint, which is worse UX.
- Timeout: retrieval can take up to `http_timeout_seconds`. We use
  httpx streaming so a slow stream isn't a hard fail.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterable

import httpx
from shared.config.settings import settings
from shared.logging.setup import get_logger
from shared.schemas.chat import (
    ChatCitationsEvent,
    ChatDoneEvent,
    ChatErrorEvent,
    ChatMessage,
    ChatTokenEvent,
    SessionEvent,
)
from shared.schemas.citations import Citation

from chat.session import SessionStore


log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────
# SSE framing (chat-side events)
# ─────────────────────────────────────────────────────────────
def _sse(event_type: str, payload: str) -> str:
    return f"event: {event_type}\ndata: {payload}\n\n"


def _session_event(session_id: str) -> str:
    return _sse("session", SessionEvent(session_id=session_id).model_dump_json())


def _token_event(text: str) -> str:
    return _sse("token", ChatTokenEvent(text=text).model_dump_json())


def _citations_event(citations: list[Citation]) -> str:
    return _sse(
        "citations",
        ChatCitationsEvent(citations=citations).model_dump_json(),
    )


def _error_event(message: str, *, retryable: bool = False) -> str:
    return _sse(
        "error",
        ChatErrorEvent(message=message, retryable=retryable).model_dump_json(),
    )


def _done_event() -> str:
    return _sse("done", ChatDoneEvent().model_dump_json())


# ─────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────
async def stream_chat(
    user_message: str,
    session_id: str | None,
    store: SessionStore,
    *,
    metadata_filter: dict | None = None,
) -> AsyncIterable[str]:
    """
    Yield SSE strings for a single chat turn.

    On any failure, emits an `error` event followed by `done`. Never
    raises — the StreamingResponse expects a clean async generator.
    """
    session, created = store.get_or_create(session_id)
    log.info(
        "chat_turn_started",
        session_id=session.session_id,
        session_created=created,
        history_len=len(session.messages),
        message_chars=len(user_message),
    )

    # 1. Emit the session id so a first-time client can capture it.
    yield _session_event(session.session_id)

    # 2. Record the user message.
    store.append(
        session.session_id,
        ChatMessage(role="user", content=user_message),
    )

    # 3. Build the retrieval payload. `recent_turns` is a flat list of
    #    prior *user* queries, oldest-first — enough context for HyDE to
    #    resolve pronouns without burying it in assistant prose.
    recent_user_turns = [
        m.content for m in session.messages if m.role == "user"
    ][-4:-1]  # exclude the current user turn

    retrieve_payload: dict = {
        "query": user_message,
        "recent_turns": recent_user_turns,
    }
    if metadata_filter:
        retrieve_payload["metadata_filter"] = metadata_filter

    # 4. Stream from retrieval.
    assistant_chunks: list[str] = []
    citations: list[Citation] = []

    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            async with client.stream(
                "POST",
                f"{settings.retrieval_url}/retrieve",
                json=retrieve_payload,
                headers={"Accept": "text/event-stream"},
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    msg = (
                        f"retrieval returned HTTP {resp.status_code}: "
                        f"{body.decode(errors='replace')[:300]}"
                    )
                    log.warning("chat_retrieval_http_error", status=resp.status_code)
                    yield _error_event(msg, retryable=resp.status_code >= 500)
                    yield _done_event()
                    return

                current_event: str | None = None
                async for line in resp.aiter_lines():
                    if not line:
                        current_event = None
                        continue

                    if line.startswith("event:"):
                        current_event = line.split(":", 1)[1].strip()
                        continue

                    if not line.startswith("data:"):
                        continue

                    payload = line.split(":", 1)[1].strip()
                    try:
                        obj = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    if current_event == "token":
                        text = obj.get("text", "")
                        if text:
                            assistant_chunks.append(text)
                            yield _token_event(text)

                    elif current_event == "citations":
                        try:
                            citations = [Citation.model_validate(c) for c in obj.get("citations", [])]
                        except Exception as exc:  # noqa: BLE001
                            log.warning("chat_citations_parse_error", error=str(exc))
                            citations = []
                        yield _citations_event(citations)

                    elif current_event == "trace":
                        # Passthrough — clients that want the trace get it.
                        yield _sse("trace", json.dumps(obj.get("trace")))

                    elif current_event == "error":
                        yield _error_event(
                            obj.get("message", "retrieval error"),
                            retryable=bool(obj.get("retryable", False)),
                        )

                    elif current_event == "done":
                        # Retrieval signals done; we emit our own after
                        # persisting the assistant reply, below.
                        pass

    except httpx.HTTPError as exc:
        log.warning("chat_retrieval_transport_error", error=str(exc))
        yield _error_event(
            f"could not reach retrieval service at {settings.retrieval_url}",
            retryable=True,
        )
        yield _done_event()
        return

    # 5. Persist the assistant reply (tokens joined) with citations.
    assistant_text = "".join(assistant_chunks).strip()

    if not assistant_text and not citations:
        log.warning("chat_empty_retrieval_response", session_id=session.session_id)
        fallback = "I wasn't able to generate an answer. Please try again."
        yield _token_event(fallback)
        assistant_text = fallback

    if assistant_text or citations:
        store.append(
            session.session_id,
            ChatMessage(
                role="assistant",
                content=assistant_text or "(no answer)",
                citations=citations,
            ),
        )

    log.info(
        "chat_turn_completed",
        session_id=session.session_id,
        tokens=len(assistant_chunks),
        citations=len(citations),
    )

    yield _done_event()


__all__ = ["stream_chat"]