"""
Reciprocal Rank Fusion (ADR-005).

Combines ranked lists from dense and sparse retrievers into a single
ranked list. RRF's score for a document d is:

    score(d) = sum over retrievers r of  1 / (k + rank_r(d))

where rank_r(d) is d's 1-indexed position in r's result list, and k is a
smoothing constant (default 60, from the original Cormack et al. 2009
paper).

Why RRF over weighted score fusion:
- Dense scores (cosine similarity, bounded [0,1]) and BM25 scores
  (unbounded, magnitude depends on corpus) are not comparable. Any
  weighted-sum approach requires per-query normalization and tuning.
- RRF uses only the *ranks*, which are always comparable, at the cost of
  ignoring score magnitude. Empirically robust.
- Zero hyperparameters to tune beyond k, which almost nobody tunes.

Design notes:
- Documents are identified by chunk_id. Two results from different
  retrievers with the same chunk_id are the same document — RRF sums
  their contributions.
- We preserve a representative ScoredChunk per chunk_id (the one from
  the retriever that ranked it highest), so downstream code can inspect
  it if needed. The final score is the RRF score, not the retriever's.
- Output is tagged `retriever="rrf"` so later stages can tell.
"""

from __future__ import annotations

from collections import defaultdict

from shared.config.settings import settings
from shared.logging.setup import get_logger
from shared.schemas.chunk import ScoredChunk

log = get_logger(__name__)


def rrf_fuse(
    ranked_lists: list[list[ScoredChunk]],
    k: int | None = None,
    top_k: int | None = None,
) -> list[ScoredChunk]:
    """
    Fuse multiple ranked lists with RRF.

    Args:
        ranked_lists: One list per retriever, each already sorted by that
            retriever's own score descending.
        k: RRF smoothing constant. Defaults to settings.rrf_k (60).
        top_k: Optional cap on the returned list length.

    Returns:
        A single list of ScoredChunk, sorted by descending RRF score,
        tagged `retriever="rrf"`.
    """
    effective_k = k if k is not None else settings.rrf_k

    scores: dict[str, float] = defaultdict(float)
    # Keep a representative chunk per id — the first one we see from a
    # retriever that placed it highest. We don't need this for scoring,
    # only to have text+metadata available downstream.
    representatives: dict[str, ScoredChunk] = {}

    for ranked in ranked_lists:
        for rank, scored in enumerate(ranked, start=1):
            cid = scored.chunk.metadata.chunk_id
            scores[cid] += 1.0 / (effective_k + rank)
            # Prefer keeping the representation from whichever retriever
            # ranked it first (i.e., highest) — but any is fine textually.
            representatives.setdefault(cid, scored)

    fused: list[ScoredChunk] = []
    for cid, score in scores.items():
        rep = representatives[cid]
        fused.append(
            ScoredChunk(
                chunk=rep.chunk,
                score=score,
                retriever="rrf",
            )
        )

    fused.sort(key=lambda s: s.score, reverse=True)
    if top_k is not None:
        fused = fused[:top_k]

    log.info(
        "rrf_fused",
        inputs=[len(lst) for lst in ranked_lists],
        unique_docs=len(scores),
        returned=len(fused),
        k=effective_k,
    )
    return fused


__all__ = ["rrf_fuse"]