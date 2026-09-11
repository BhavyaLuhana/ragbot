"""
Ollama provider implementations of the Protocols (ADR-016, ADR-022).

Two classes:
- OllamaEmbeddingProvider — wraps `AsyncClient.embeddings` (nomic-embed-text)
- OllamaLLMProvider       — wraps `AsyncClient.chat` with stream=True

Design mirrors openai_provider.py:
- Client injected at construction.
- All SDK exceptions wrapped in ProviderError with retryable flag.
- Batching is an internal detail of embed().
- stream() yields raw token strings — SSE formatting is the caller's job.

Notes specific to Ollama:
- The Python client (>=0.4) has a native AsyncClient — no httpx shim needed.
- Ollama batches at the *model* level, but the Python client issues one
  HTTP request per input in embeddings — we still batch at our own
  BATCH_SIZE boundary to allow future providers to coalesce if needed.
- `nomic-embed-text` prepends a task prefix (`search_document: ` /
  `search_query: `) internally per the model card. We don't add prefixes
  ourselves; Ollama handles it.
"""

from __future__ import annotations

from typing import AsyncIterable

from ollama import AsyncClient, ResponseError

from shared.providers.base import ProviderError


# Ollama handles one HTTP request per input; batch sizes under ~1000 keep
# individual request latency predictable and avoid huge payloads.
EMBED_BATCH_SIZE = 500


# ─────────────────────────────────────────────────────────────
# Error translation
# ─────────────────────────────────────────────────────────────
def _translate_ollama_error(exc: Exception, *, provider_name: str) -> ProviderError:
    """
    Map an ollama SDK exception to a ProviderError.

    Retryable = transient conditions where a retry has a real chance:
    connection failures (Ollama not running yet, still loading model),
    timeouts, 5xx.

    Non-retryable = 404 (model not pulled), 400 (malformed request).
    """
    if isinstance(exc, ResponseError):
        status = getattr(exc, "status_code", None)
        # Ollama returns 404 when the requested model isn't pulled.
        if status == 404:
            return ProviderError(
                provider_name,
                f"model not found — did you `ollama pull` it? ({exc})",
                retryable=False,
            )
        if status is not None and status >= 500:
            return ProviderError(
                provider_name, f"HTTP {status}: {exc}", retryable=True
            )
        return ProviderError(
            provider_name, f"HTTP {status}: {exc}", retryable=False
        )

    if isinstance(exc, ConnectionError):
        # Ollama not running, or startup in progress.
        return ProviderError(
            provider_name,
            f"cannot reach Ollama at configured URL — is it running? ({exc})",
            retryable=True,
        )

    if isinstance(exc, TimeoutError):
        return ProviderError(provider_name, f"timeout: {exc}", retryable=True)

    return ProviderError(provider_name, f"unexpected error: {exc!r}", retryable=False)


# ─────────────────────────────────────────────────────────────
# Embeddings
# ─────────────────────────────────────────────────────────────
class OllamaEmbeddingProvider:
    """EmbeddingProvider backed by Ollama's embeddings endpoint."""

    def __init__(
        self,
        client: AsyncClient,
        model: str = "nomic-embed-text",
        dimension: int = 768,
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
        if not texts:
            return []

        results: list[list[float]] = []
        for i in range(0, len(texts), EMBED_BATCH_SIZE):
            batch = texts[i : i + EMBED_BATCH_SIZE]
            results.extend(await self._embed_batch(batch))
        return results

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self._embed_batch([text])
        return vectors[0]

    # ── private ──────────────────────────────────────────────
    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        """
        One embeddings call per input (Ollama client API contract),
        gathering concurrently. Order is preserved via asyncio.gather.
        """
        import asyncio

        async def _one(text: str) -> list[float]:
            try:
                response = await self._client.embeddings(
                    model=self._model, prompt=text
                )
            except Exception as exc:  # noqa: BLE001 — boundary
                raise _translate_ollama_error(
                    exc, provider_name="ollama.embeddings"
                ) from exc
            # Ollama SDK returns an object with `.embedding: list[float]`
            return list(response.embedding)

        return await asyncio.gather(*(_one(t) for t in batch))


# ─────────────────────────────────────────────────────────────
# LLM
# ─────────────────────────────────────────────────────────────
class OllamaLLMProvider:
    """LLMProvider backed by Ollama's chat endpoint."""

    def __init__(
        self,
        client: AsyncClient,
        model: str = "llama3.2",
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
        try:
            response = await self._client.chat(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                options={
                    "temperature": (
                        temperature
                        if temperature is not None
                        else self._default_temperature
                    ),
                    "num_predict": (
                        max_tokens
                        if max_tokens is not None
                        else self._default_max_tokens
                    ),
                },
            )
        except Exception as exc:  # noqa: BLE001
            raise _translate_ollama_error(exc, provider_name="ollama.chat") from exc

        # Ollama SDK returns a dict-like or pydantic-like object.
        # `response.message.content` (attribute) or `response["message"]["content"]`
        # both work — we prefer attribute access for the >=0.4 SDK.
        return response.message.content or ""

    def stream(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterable[str]:
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
            response = await self._client.chat(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                options={
                    "temperature": (
                        temperature
                        if temperature is not None
                        else self._default_temperature
                    ),
                    "num_predict": (
                        max_tokens
                        if max_tokens is not None
                        else self._default_max_tokens
                    ),
                },
                stream=True,
            )
        except Exception as exc:  # noqa: BLE001
            raise _translate_ollama_error(exc, provider_name="ollama.chat") from exc

        try:
            async for chunk in response:
                # Ollama chat stream chunks: {"message": {"content": "..."}, ...}
                # Empty-content chunks appear on role-only or done frames.
                content = chunk.message.content if chunk.message else None
                if not content:
                    continue
                yield content
        except Exception as exc:  # noqa: BLE001
            raise _translate_ollama_error(exc, provider_name="ollama.chat") from exc