"""
Answer generation + SSE event formatting.

Given a query and the final top-K reranked chunks, build a prompt for
the LLM and stream the answer back as SSE events:

    event: token      data: {"type": "token", "text": "..."}
    event: citations  data: {"type": "citations", "citations": [...]}
    event: trace      data: {"type": "trace", "trace": {...}}
    event: done       data: {"type": "done"}

Design notes:
- The LLMProvider yields raw token strings (per shared/providers/base.py).
  This module is the *only* place that knows about SSE framing — the
  provider stays provider-agnostic, and the app stays agnostic about the
  wire format.
- Citations and trace are sent AFTER the token stream completes. That
  matches the UX: the answer appears token-by-token, then source pills
  render underneath.
- We refuse gracefully when there are no retrieved chunks: emit a single
  canned token and a done event, no LLM call.
- On provider error mid-stream: emit an "error" event, then "done".
  The client can show "response interrupted, retry?" without a hard
  failure.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterable

from shared.logging.setup import get_logger
from shared.providers.base import LLMProvider, ProviderError
from shared.schemas.chunk import ScoredChunk
from shared.schemas.citations import Citation
from shared.schemas.retrieve import (
    CitationsEvent,
    DoneEvent,
    ErrorEvent,
    StageTrace,
    TokenEvent,
    TraceEvent,
)

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────
# Prompt
# ─────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You answer questions using ONLY the provided context from an internal
engineering handbook. Follow these rules strictly:

1. If the context contains the answer, answer concisely in 2 to 4
   sentences. Cite pages inline like "(p. 4)".
2. If the context does not contain the answer, say so explicitly —
   do NOT make anything up.
3. Do NOT reference "the context" or "the provided documents" — just
   answer as if you know the material.
4. If you use multiple sources, weave them naturally; don't list them.
"""


def _format_context(chunks: list[ScoredChunk]) -> str:
    """
    Format retrieved chunks with a stable, LLM-friendly layout.

    Each block is:
        [p{page} §{section}]
        {text}

    Section is omitted if empty. Page is always included so the model can
    cite inline.
    """
    blocks: list[str] = []
    for sc in chunks:
        m = sc.chunk.metadata
        header_bits = [f"p{m.page}"]
        if m.section:
            header_bits.append(f"§{m.section}")
        header = f"[{' '.join(header_bits)}]"
        blocks.append(f"{header}\n{sc.chunk.text}")
    return "\n\n".join(blocks)


def build_prompt(query: str, chunks: list[ScoredChunk]) -> str:
    context = _format_context(chunks)
    return (
        f"{_SYSTEM_PROMPT}\n\n"
        f"Context:\n{context}\n\n"
        f"Question: {query}\n\n"
        f"Answer:"
    )


# ─────────────────────────────────────────────────────────────
# SSE framing
# ─────────────────────────────────────────────────────────────
def _sse(event_type: str, payload: str) -> str:
    """
    Frame an SSE message.

    Format required by the SSE spec:
        event: <type>\n
        data: <json>\n
        \n
    The final blank line terminates the event.
    """
    return f"event: {event_type}\ndata: {payload}\n\n"


def _token_event(text: str) -> str:
    return _sse("token", TokenEvent(text=text).model_dump_json())


def _citations_event(citations: list[Citation]) -> str:
    return _sse("citations", CitationsEvent(citations=citations).model_dump_json())


def _trace_event(trace: StageTrace) -> str:
    return _sse("trace", TraceEvent(trace=trace).model_dump_json())


def _error_event(message: str, *, retryable: bool = False) -> str:
    return _sse("error", ErrorEvent(message=message, retryable=retryable).model_dump_json())


def _done_event() -> str:
    return _sse("done", DoneEvent().model_dump_json())


# ─────────────────────────────────────────────────────────────
# Streaming generator
# ─────────────────────────────────────────────────────────────
async def stream_answer(
    query: str,
    chunks: list[ScoredChunk],
    llm: LLMProvider,
    *,
    trace: StageTrace | None = None,
    max_tokens: int | None = None,
) -> AsyncIterable[str]:
    """
    Yield SSE-framed strings: tokens, then citations, then done.

    The caller (FastAPI StreamingResponse) just forwards each yielded
    string to the client verbatim.
    """
    if not chunks:
        # No retrieval hits — refuse without calling the LLM.
        refusal = (
            "I couldn't find anything in the handbook that answers that "
            "question."
        )
        yield _token_event(refusal)
        if trace is not None:
            yield _trace_event(trace)
        yield _done_event()
        return

    prompt = build_prompt(query, chunks)
    saw_any_token = False

    try:
        async for token in llm.stream(prompt, max_tokens=max_tokens):
            if token:
                saw_any_token = True
                yield _token_event(token)
    except ProviderError as exc:
        log.warning(
            "generate_provider_error",
            provider=exc.provider,
            retryable=exc.retryable,
            error=str(exc),
        )
        yield _error_event(str(exc), retryable=exc.retryable)
        yield _done_event()
        return
    except Exception as exc:  # noqa: BLE001
        log.exception("generate_unexpected_error", error=str(exc))
        yield _error_event("internal error while generating answer", retryable=False)
        yield _done_event()
        return

    citations = [Citation.from_chunk(sc.chunk, score=sc.score) for sc in chunks]
    yield _citations_event(citations)

    if trace is not None:
        yield _trace_event(trace)

    if not saw_any_token:
        log.warning(
            "generate_empty_stream",
            chunks=len(chunks),
            prompt_chars=len(prompt),
            llm=llm.model_name,
        )
        yield _token_event(
            "I wasn't able to generate an answer. Please try again."
        )
    else:
        log.info("generate_stream_complete")

    yield _done_event()


__all__ = [
    "build_prompt",
    "stream_answer",
]