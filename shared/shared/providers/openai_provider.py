"""
Concrete OpenAI implementations of the provider Protocols (ADR-016).

Two classes:
- OpenAIEmbeddingProvider — wraps `client.embeddings.create`
- OpenAILLMProvider       — wraps `client.chat.completions.create`
                            (both complete() and stream() modes)

Design notes:
- One AsyncOpenAI client per provider instance, injected at construction
  so tests can pass a fake and services can share a client if needed.
- Every SDK exception is translated to `ProviderError` with a
  `retryable` flag so upstream retry logic has a single thing to check.
- Batching for embeddings is an implementation detail of `embed()` —
  the caller passes any-size list and gets back 1:1 results.
- No prompt templating here. Prompts arrive as rendered strings.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterable

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)

from shared.providers.base import ProviderError


# OpenAI accepts up to 2048 inputs per embeddings request. We stay well
# under to leave headroom for token-count limits on large chunks.
EMBED_BATCH_SIZE = 500


# ─────────────────────────────────────────────────────────────
# Error translation
# ─────────────────────────────────────────────────────────────
def _translate_openai_error(exc: Exception, *, provider_name: str) -> ProviderError:
    """
    Map an OpenAI SDK exception to a ProviderError.

    Retryable = transient conditions where a second attempt has a real
    chance of succeeding (rate limit, timeout, 5xx, network).
    Non-retryable = auth, malformed request, 4xx that won't change on retry.
    """
    if isinstance(exc, RateLimitError):
        return ProviderError(provider_name, f"rate limited: {exc}", retryable=True)
    if isinstance(exc, APITimeoutError):
        return ProviderError(provider_name, f"timeout: {exc}", retryable=True)
    if isinstance(exc, APIConnectionError):
        return ProviderError(provider_name, f"connection error: {exc}", retryable=True)
    if isinstance(exc, APIStatusError):
        # 5xx → retryable, other 4xx → not
        retryable = exc.status_code >= 500
        return ProviderError(
            provider_name,
            f"HTTP {exc.status_code}: {exc}",
            retryable=retryable,
        )
    if isinstance(exc, AuthenticationError):
        return ProviderError(provider_name, f"auth failed: {exc}", retryable=False)
    if isinstance(exc, BadRequestError):
        return ProviderError(provider_name, f"bad request: {exc}", retryable=False)
    # Unknown → don't retry blindly
    return ProviderError(provider_name, f"unexpected error: {exc!r}", retryable=False)


# ─────────────────────────────────────────────────────────────
# Embeddings
# ─────────────────────────────────────────────────────────────
class OpenAIEmbeddingProvider:
    """EmbeddingProvider backed by OpenAI's embeddings endpoint."""

    def __init__(
        self,
        client: AsyncOpenAI,
        model: str = "text-embedding-3-small",
        dimension: int = 1536,
    ) -> None:
        self._client = client
        self._model = model
        self._dimension = dimension

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a batch of texts, chunked into EMBED_BATCH_SIZE-sized
        sub-batches to respect the API's per-request limit.

        Order is preserved across sub-batches. Empty input → empty output
        (no API call made).
        """
        if not texts:
            return []

        results: list[list[float]] = []
        for i in range(0, len(texts), EMBED_BATCH_SIZE):
            batch = texts[i : i + EMBED_BATCH_SIZE]
            results.extend(await self._embed_batch(batch))
        return results

    async def embed_query(self, text: str) -> list[float]:
        """Single-string embed for the retrieval path."""
        vectors = await self._embed_batch([text])
        return vectors[0]

    # ── private ──────────────────────────────────────────────
    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        """One SDK call. Expects 0 < len(batch) <= EMBED_BATCH_SIZE."""
        try:
            response = await self._client.embeddings.create(
                model=self._model,
                input=batch,
            )
        except Exception as exc:  # noqa: BLE001 — deliberate boundary
            raise _translate_openai_error(exc, provider_name="openai.embeddings") from exc

        # OpenAI returns items with an `index` field; sort defensively so
        # output order always matches input order even if the API reorders.
        ordered = sorted(response.data, key=lambda item: item.index)
        return [item.embedding for item in ordered]


# ─────────────────────────────────────────────────────────────
# LLM
# ─────────────────────────────────────────────────────────────
class OpenAILLMProvider:
    """LLMProvider backed by OpenAI's chat completions endpoint."""

    def __init__(
        self,
        client: AsyncOpenAI,
        model: str = "gpt-4o-mini",
        default_temperature: float = 0.0,
        default_max_tokens: int = 800,
    ) -> None:
        self._client = client
        self._model = model
        self._default_temperature = default_temperature
        self._default_max_tokens = default_max_tokens

    @property
    def model_name(self) -> str:
        return self._model

    async def complete(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """One-shot completion. Returns the assistant message content."""
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=(
                    temperature if temperature is not None else self._default_temperature
                ),
                max_tokens=(
                    max_tokens if max_tokens is not None else self._default_max_tokens
                ),
            )
        except Exception as exc:  # noqa: BLE001
            raise _translate_openai_error(exc, provider_name="openai.chat") from exc

        content = response.choices[0].message.content
        return content or ""

    def stream(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterable[str]:
        """
        Streaming completion. Yields raw token strings.

        Note: this is `async def` combined with `yield`, which makes the
        whole method an async generator — the caller awaits each token via
        `async for`. Errors raised here bubble up mid-iteration as
        ProviderError, which the SSE layer catches and emits as an
        `{"type": "error", ...}` event.
        """
        return self._stream_impl(
            prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    # ── private ──────────────────────────────────────────────
    async def _stream_impl(
        self,
        prompt: str,
        *,
        temperature: float | None,
        max_tokens: int | None,
    ) -> AsyncIterable[str]:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=(
                    temperature if temperature is not None else self._default_temperature
                ),
                max_tokens=(
                    max_tokens if max_tokens is not None else self._default_max_tokens
                ),
                stream=True,
            )
        except Exception as exc:  # noqa: BLE001
            raise _translate_openai_error(exc, provider_name="openai.chat") from exc

        try:
            async for chunk in response:
                # Defensive: some chunks carry only a role or finish_reason
                # and have empty choices. Skip rather than crash.
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta is None or delta.content is None:
                    continue
                yield delta.content
        except Exception as exc:  # noqa: BLE001
            raise _translate_openai_error(exc, provider_name="openai.chat") from exc
        finally:
            # Ensure the underlying HTTP stream is closed even if the
            # consumer stops iterating early (e.g. client disconnect).
            await asyncio.shield(response.close())