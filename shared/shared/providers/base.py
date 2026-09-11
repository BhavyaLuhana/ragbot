"""
Provider abstraction layer (ADR-016).

Defines the Protocol interfaces that every LLM and embedding provider must
satisfy. Services depend on these Protocols, never on a concrete SDK.

Why Protocols (not ABCs):
- Structural typing — providers don't need to inherit from us.
- Third-party SDK wrappers can satisfy the shape without modification.
- Tests can inject fakes trivially.

Streaming contract:
- `LLMProvider.stream()` yields RAW token strings.
- Structured SSE event formatting ({"type": "token", ...}) is the
  transport layer's job (retrieval/generate.py), not the provider's.
- This keeps providers portable: OpenAI, Anthropic, Ollama all yield
  plain tokens natively, so no per-provider event schema translation.
"""

from __future__ import annotations

from typing import AsyncIterable, Protocol, runtime_checkable


# ─────────────────────────────────────────────────────────────
# Embeddings
# ─────────────────────────────────────────────────────────────
@runtime_checkable
class EmbeddingProvider(Protocol):
    """
    Embeds text into dense vectors.

    Implementations must be safe to call concurrently from asyncio tasks.
    Batching is the caller's responsibility; providers process lists in
    the order given.
    """

    @property
    def model_name(self) -> str:
        """Human-readable model identifier (e.g. 'text-embedding-3-small')."""
        ...

    @property
    def dimension(self) -> int:
        """Output vector dimensionality. Used for Chroma collection setup."""
        ...

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a batch of texts.

        Args:
            texts: Non-empty list of strings. Empty strings are allowed but
                provider-dependent in behavior; callers should filter them.

        Returns:
            List of float vectors, same order and length as `texts`.

        Raises:
            ProviderError: On transport, auth, or rate-limit failures.
        """
        ...

    async def embed_query(self, text: str) -> list[float]:
        """
        Embed a single query string.

        Separate method (not just `embed([text])[0]`) because some providers
        use a different model or prefix for queries vs. documents
        (e.g. E5, BGE). OpenAI treats them identically, but keeping the
        distinction in the Protocol keeps us portable.
        """
        ...


# ─────────────────────────────────────────────────────────────
# LLM
# ─────────────────────────────────────────────────────────────
@runtime_checkable
class LLMProvider(Protocol):
    """
    Generates text from a prompt.

    Two modes:
    - `complete()` — one-shot, returns the full string. Used by HyDE,
      synthetic eval generation, and the non-streaming /retrieve/sync path.
    - `stream()`   — yields raw token strings as they arrive. Used by the
      SSE path in retrieval/generate.py.

    Both methods take a single already-rendered prompt string. Prompt
    templating belongs to the caller (retrieval/generate.py), not the
    provider — so we can version prompts independently of providers.
    """

    @property
    def model_name(self) -> str:
        """Human-readable model identifier (e.g. 'gpt-4o-mini')."""
        ...

    async def complete(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """
        Generate a full completion.

        Args:
            prompt: Fully rendered prompt string.
            temperature: Override default; None uses provider default.
            max_tokens: Override default; None uses provider default.

        Returns:
            The generated text (no prompt echo).

        Raises:
            ProviderError: On transport, auth, rate-limit, or content failures.
        """
        ...

    def stream(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterable[str]:
        """
        Stream a completion token-by-token.

        Yields:
            Raw token strings, in generation order. No wrapping, no events,
            no metadata. The SSE layer is responsible for formatting.

        Notes:
            - Returns an AsyncIterable (not a coroutine). Callers do
              `async for token in provider.stream(prompt): ...`
            - Empty strings are allowed (some providers emit them for
              whitespace-only deltas) — callers may skip them if desired.
            - The final yielded chunk may be a partial token depending on
              provider tokenization. Callers should not assume
              word-boundary integrity.

        Raises:
            ProviderError: On transport, auth, rate-limit, or content failures.
        """
        ...


# ─────────────────────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────────────────────
class ProviderError(RuntimeError):
    """
    Raised by any provider implementation on unrecoverable failure.

    Services catch this at the boundary and translate to:
    - HTTP 502 for API responses
    - SSE `{"type": "error", "message": ...}` events for streaming
    - Degraded fallbacks (e.g. skip HyDE, use raw query) where safe
    """

    def __init__(self, provider: str, message: str, *, retryable: bool = False):
        super().__init__(f"[{provider}] {message}")
        self.provider = provider
        self.retryable = retryable


# ─────────────────────────────────────────────────────────────
# Exports
# ─────────────────────────────────────────────────────────────
__all__ = [
    "EmbeddingProvider",
    "LLMProvider",
    "ProviderError",
]