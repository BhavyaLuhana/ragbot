"""
Provider factory (ADR-016, ADR-022).

Reads `settings.embedding_provider` / `settings.llm_provider` and returns
the matching concrete provider. Services never instantiate providers
directly — they call `get_embedding_provider()` / `get_llm_provider()`.

Adding a new provider = new class in this folder + one `if` branch here +
one value added to the `Literal[...]` in settings.py. No service code
changes.
"""

from __future__ import annotations

from functools import lru_cache

import ollama
from openai import AsyncOpenAI

from shared.config.settings import settings
from shared.providers.base import EmbeddingProvider, LLMProvider
from shared.providers.ollama_provider import (
    OllamaEmbeddingProvider,
    OllamaLLMProvider,
)
from shared.providers.openai_provider import (
    OpenAIEmbeddingProvider,
    OpenAILLMProvider,
)


# ─────────────────────────────────────────────────────────────
# Shared clients (one per process, per provider family)
# ─────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _ollama_client() -> ollama.AsyncClient:
    """Singleton Ollama async client. No key needed — just a URL."""
    return ollama.AsyncClient(host=settings.ollama_url)


@lru_cache(maxsize=1)
def _openai_client() -> AsyncOpenAI:
    """
    Singleton OpenAI client. Constructed lazily so importing this module
    doesn't require a key — only selecting the OpenAI provider does.
    """
    return AsyncOpenAI(api_key=settings.require_openai_key())


# ─────────────────────────────────────────────────────────────
# Factories
# ─────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider:
    """Return the configured embedding provider (cached)."""
    name = settings.embedding_provider
    if name == "ollama":
        return OllamaEmbeddingProvider(
            client=_ollama_client(),
            model=settings.embedding_model,
            dimension=settings.embedding_dim,
        )
    if name == "openai":
        return OpenAIEmbeddingProvider(
            client=_openai_client(),
            model=settings.openai_embedding_model,
            dimension=settings.openai_embedding_dim,
        )
    raise ValueError(f"Unknown embedding provider: {name!r}")


@lru_cache(maxsize=1)
def get_llm_provider() -> LLMProvider:
    """Return the configured LLM provider (cached)."""
    name = settings.llm_provider
    if name == "ollama":
        return OllamaLLMProvider(
            client=_ollama_client(),
            model=settings.llm_model,
            default_temperature=settings.llm_temperature,
            default_max_tokens=settings.llm_max_tokens,
        )
    if name == "openai":
        return OpenAILLMProvider(
            client=_openai_client(),
            model=settings.openai_llm_model,
            default_temperature=settings.llm_temperature,
            default_max_tokens=settings.llm_max_tokens,
        )
    raise ValueError(f"Unknown LLM provider: {name!r}")


__all__ = [
    "get_embedding_provider",
    "get_llm_provider",
]