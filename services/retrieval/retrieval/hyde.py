"""
HyDE — Hypothetical Document Embeddings (ADR-007).

For a short user query, ask an LLM to write a hypothetical *passage*
that would answer it. Embed that passage instead of the raw query for
dense retrieval. The hypothesis is often a better match to real
documents than the short question is.

Reference: Gao et al., "Precise Zero-Shot Dense Retrieval without
Relevance Labels" (2022).

Design notes:
- HyDE applies to DENSE retrieval only (per decision A). Sparse uses the
  raw query so it keeps exact-match strength on acronyms, IDs, and
  section names the user actually typed.
- Failure is non-fatal: if the LLM call fails, we fall back to the raw
  query and log a warning. Retrieval still works, just with less lift.
- We include recent turns (optional) as context for the rewrite so
  follow-up questions like "and what about rollback?" resolve pronouns
  correctly.

Prompt design: we ask for a passage, not a Q&A, and instruct the model
to be concise (3–6 sentences) so we don't waste embedding tokens.
"""

from __future__ import annotations

from shared.logging.setup import get_logger
from shared.providers.base import LLMProvider, ProviderError

log = get_logger(__name__)


_HYDE_SYSTEM_PROMPT = """\
You write short, factual passages that would answer a user's question
based on an internal engineering handbook. The passage you write will be
embedded and used to search the handbook for real matching content.

Rules:
- Write 3 to 6 sentences.
- Use the vocabulary and tone of an internal engineering handbook.
- Do NOT preface with "Sure" or "Here is..." — write only the passage.
- If the question is ambiguous, pick the most likely interpretation and
  write a passage for it.
"""


def _build_hyde_prompt(query: str, recent_turns: list[str] | None) -> str:
    if not recent_turns:
        return f"Question: {query}\n\nPassage:"

    history = "\n".join(f"- {turn}" for turn in recent_turns[-4:])
    return (
        "Recent conversation (oldest first):\n"
        f"{history}\n\n"
        f"Current question: {query}\n\n"
        "Write a passage that answers the current question.\n\nPassage:"
    )


async def generate_hyde(
    query: str,
    llm: LLMProvider,
    *,
    recent_turns: list[str] | None = None,
    max_tokens: int = 200,
) -> tuple[str, bool]:
    """
    Return (hypothetical_passage, used_hyde: bool).

    On success: (hyde_text, True). On failure: (query, False) — so the
    caller can safely use the return value as the effective query
    regardless of what happened.
    """
    if not query.strip():
        return query, False

    prompt = _build_hyde_prompt(query, recent_turns)
    full_prompt = f"{_HYDE_SYSTEM_PROMPT}\n\n{prompt}"

    try:
        hyde_text = await llm.complete(full_prompt, max_tokens=max_tokens)
    except ProviderError as exc:
        log.warning(
            "hyde_provider_error",
            retryable=exc.retryable,
            error=str(exc),
            fallback="raw_query",
        )
        return query, False
    except Exception as exc:  # noqa: BLE001
        log.warning("hyde_unexpected_error", error=str(exc), fallback="raw_query")
        return query, False

    hyde_text = (hyde_text or "").strip()
    if not hyde_text:
        log.warning("hyde_empty_response", fallback="raw_query")
        return query, False

    log.info(
        "hyde_generated",
        query_chars=len(query),
        hyde_chars=len(hyde_text),
        hyde_preview=hyde_text[:120],
    )
    return hyde_text, True


__all__ = ["generate_hyde"]