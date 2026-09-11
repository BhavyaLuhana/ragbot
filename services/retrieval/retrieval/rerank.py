"""
Cross-encoder reranker (ADR-006).

Takes a small candidate set (top-N from RRF, N ~20) and re-scores each
(candidate_text, query) pair with a cross-encoder model. Returns the
top-K by cross-encoder score.

Why cross-encoder over bi-encoder for reranking:
- Bi-encoder (dense retrieval) embeds query and document independently.
  Fast, but the query never "sees" the document.
- Cross-encoder reads query + document together, attends across both,
  and produces a much sharper relevance score. Slow per pair — fine for
  20 candidates, catastrophic for 100k.

Model: cross-encoder/ms-marco-MiniLM-L-6-v2. ~90MB, CPU-fast, well
benchmarked on MS MARCO passage ranking.

Design notes:
- The model is loaded once at service startup (warm cache). First
  inference after load takes ~1-2s; subsequent ~50ms per candidate.
- sentence-transformers' CrossEncoder.predict is synchronous and
  CPU-bound — we run it in a thread pool so we don't block the event
  loop of the FastAPI server.
- Scores are raw logits (unbounded). We don't normalize — RRF already
  handled rank fusion; rerank just re-orders.
"""

from __future__ import annotations

import asyncio
from functools import partial

from sentence_transformers import CrossEncoder
from shared.config.settings import settings
from shared.logging.setup import get_logger
from shared.schemas.chunk import ScoredChunk

log = get_logger(__name__)


class Reranker:
    """Cross-encoder reranker. Loaded once, called many times."""

    def __init__(self, model_name: str | None = None, device: str | None = None) -> None:
        self._model_name = model_name or settings.reranker_model
        self._device = device or settings.reranker_device
        log.info("reranker_loading", model=self._model_name, device=self._device)
        self._model = CrossEncoder(self._model_name, device=self._device)
        log.info("reranker_ready", model=self._model_name)

    @property
    def model_name(self) -> str:
        return self._model_name

    async def rerank(
        self,
        query: str,
        candidates: list[ScoredChunk],
        top_k: int = 5,
    ) -> list[ScoredChunk]:
        """
        Score (query, candidate.text) pairs, return top_k by score desc.

        Empty candidates → empty list. Fewer candidates than top_k →
        returns all, sorted.
        """
        if not candidates:
            return []

        pairs = [(query, c.chunk.text) for c in candidates]

        # CrossEncoder.predict is blocking CPU work. Offload to a thread
        # so we don't stall the asyncio loop for other requests.
        loop = asyncio.get_running_loop()
        scores = await loop.run_in_executor(
            None,
            partial(self._model.predict, pairs, show_progress_bar=False),
        )

        # `scores` is a numpy array; float() to detach from numpy types.
        scored = [
            ScoredChunk(
                chunk=c.chunk,
                score=float(s),
                retriever="rerank",
            )
            for c, s in zip(candidates, scores)
        ]
        scored.sort(key=lambda s: s.score, reverse=True)

        log.info(
            "rerank_done",
            candidates=len(candidates),
            returned=min(top_k, len(scored)),
            top_score=scored[0].score if scored else None,
        )
        return scored[:top_k]


__all__ = ["Reranker"]