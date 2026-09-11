"""
Smoke test for the `shared/` package.

Verifies:
1. Every module imports cleanly.
2. Settings loads from .env with expected defaults.
3. Providers instantiate without needing an API call.
4. Schemas serialize / deserialize and enforce validation.

Run from repo root:  python scripts/smoke_test_shared.py
Exits 0 on success, 1 on failure with a clear traceback.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

# Ensure repo root is on sys.path when run as a script (belt-and-suspenders
# with the editable install).
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


PASS = "\033[92m✅\033[0m"
FAIL = "\033[91m❌\033[0m"


def check(label: str, fn) -> bool:
    try:
        fn()
        print(f"{PASS} {label}")
        return True
    except Exception:
        print(f"{FAIL} {label}")
        traceback.print_exc()
        return False


# ─────────────────────────────────────────────────────────────
# 1. Imports
# ─────────────────────────────────────────────────────────────
def _import_config() -> None:
    from shared.config.settings import Settings, get_settings, settings
    assert settings is not None
    assert get_settings() is settings  # lru_cache singleton
    assert Settings is not None

def _import_providers() -> None:
    from shared.providers import (
        EmbeddingProvider,
        LLMProvider,
        ProviderError,
        get_embedding_provider,
        get_llm_provider,
    )
    assert EmbeddingProvider and LLMProvider and ProviderError
    assert get_embedding_provider and get_llm_provider

def _import_schemas() -> None:
    from shared.schemas import (
        Chunk, ChunkMetadata, ScoredChunk,
        Citation,
        IngestRequest, IngestResponse, IngestStats, CollectionInfo,
        MetadataFilter, RetrieveRequest, RetrieveResponse, StageTrace,
        SSEEvent, TokenEvent, CitationsEvent, TraceEvent, ErrorEvent, DoneEvent,
        ChatMessage, ChatRequest, SessionResponse,
        SessionEvent, ChatTokenEvent, ChatCitationsEvent, ChatErrorEvent, ChatDoneEvent,
    )
    assert all(x is not None for x in (
        Chunk, ChunkMetadata, ScoredChunk, Citation,
        IngestRequest, IngestResponse, IngestStats, CollectionInfo,
        MetadataFilter, RetrieveRequest, RetrieveResponse, StageTrace,
        SSEEvent, TokenEvent, CitationsEvent, TraceEvent, ErrorEvent, DoneEvent,
        ChatMessage, ChatRequest, SessionResponse,
        SessionEvent, ChatTokenEvent, ChatCitationsEvent, ChatErrorEvent, ChatDoneEvent,
    ))

def _import_logging() -> None:
    from shared.logging.setup import configure_logging, get_logger
    assert configure_logging and get_logger


# ─────────────────────────────────────────────────────────────
# 2. Settings behaviour
# ─────────────────────────────────────────────────────────────
def _settings_paths_resolve() -> None:
    from shared.config.settings import settings
    assert settings.repo_root.is_dir(), f"repo_root missing: {settings.repo_root}"
    assert settings.data_dir.is_dir(), f"data_dir missing: {settings.data_dir}"
    assert settings.raw_dir.is_dir(), f"raw_dir missing: {settings.raw_dir}"
    assert settings.source_pdf.parent == settings.raw_dir
    # The actual PDF may not exist if you haven't placed it — warn, don't fail.
    if not settings.source_pdf.is_file():
        print(f"   ⚠️  source_pdf not found yet: {settings.source_pdf}")

def _settings_env_loaded() -> None:
    from shared.config.settings import settings
    assert settings.environment in ("local", "ci", "prod")
    assert settings.log_level in ("DEBUG", "INFO", "WARNING", "ERROR")
    assert settings.chunk_size > settings.chunk_overlap
    assert settings.rrf_k > 0
    assert settings.embedding_model
    assert settings.llm_model

def _settings_api_key_handling() -> None:
    from shared.config.settings import settings
    # The key may or may not be set. If unset, require_openai_key() should
    # raise a clear error, not an AttributeError.
    if settings.openai_api_key is None:
        try:
            settings.require_openai_key()
        except RuntimeError as e:
            assert "OPENAI_API_KEY" in str(e)
        else:
            raise AssertionError("require_openai_key() should have raised")
    else:
        key = settings.require_openai_key()
        assert isinstance(key, str) and len(key) > 0


# ─────────────────────────────────────────────────────────────
# 3. Providers instantiate (no API call)
# ─────────────────────────────────────────────────────────────
def _providers_constructible() -> None:
    """Instantiate providers per config. No live API calls."""
    from shared.config.settings import settings
    from shared.providers import get_embedding_provider, get_llm_provider
    from shared.providers import EmbeddingProvider, LLMProvider

    emb = get_embedding_provider()
    llm = get_llm_provider()

    assert emb.model_name, "embedding provider has no model_name"
    assert emb.dimension > 0, "embedding provider has no dimension"
    assert llm.model_name, "llm provider has no model_name"

    assert isinstance(emb, EmbeddingProvider)
    assert isinstance(llm, LLMProvider)

    print(
        f"   ℹ️  embedding: {settings.embedding_provider} / {emb.model_name} ({emb.dimension}d)"
    )
    print(f"   ℹ️  llm: {settings.llm_provider} / {llm.model_name}")


# ─────────────────────────────────────────────────────────────
# 4. Schemas round-trip
# ─────────────────────────────────────────────────────────────
def _schema_chunk_roundtrip() -> None:
    from shared.schemas import Chunk, ChunkMetadata, ScoredChunk
    meta = ChunkMetadata(
        chunk_id="abc-123",
        source="TechCorp_Internal_Engineering_Handbook.pdf",
        page=12,
        section="Deployment Policy",
        chunk_index=34,
        char_start=1000,
        char_end=1800,
        doc_hash="a" * 64,
    )
    chunk = Chunk(text="We deploy on Tuesdays.", metadata=meta)
    encoded = chunk.model_dump_json()
    decoded = Chunk.model_validate_json(encoded)
    assert decoded == chunk
    scored = ScoredChunk(chunk=chunk, score=0.87, retriever="rerank")
    assert scored.retriever == "rerank"
    # metadata is frozen
    try:
        meta.page = 99  # type: ignore[misc]
    except Exception:
        pass
    else:
        raise AssertionError("ChunkMetadata should be frozen")

def _schema_citation_from_chunk() -> None:
    from shared.schemas import Chunk, ChunkMetadata, Citation
    chunk = Chunk(
        text="Deployments require two approvals before merging to main. " * 5,
        metadata=ChunkMetadata(
            chunk_id="abc-123",
            source="TechCorp_Internal_Engineering_Handbook.pdf",
            page=12,
            section="Deployment Policy",
            chunk_index=34,
            char_start=1000,
            char_end=1800,
            doc_hash="a" * 64,
        ),
    )
    cite = Citation.from_chunk(chunk, score=0.91)
    assert cite.chunk_id == "abc-123"
    assert cite.page == 12
    assert cite.section == "Deployment Policy"
    assert cite.snippet.endswith("…") or len(cite.snippet) <= 240

def _schema_retrieve_roundtrip() -> None:
    from shared.schemas import (
        MetadataFilter, RetrieveRequest, RetrieveResponse, StageTrace,
        Chunk, ChunkMetadata, ScoredChunk, Citation,
    )
    req = RetrieveRequest(
        query="What is the deploy policy?",
        top_k=5,
        metadata_filter=MetadataFilter(page_gte=10, page_lte=20),
        recent_turns=["hello", "hi"],
    )
    assert req.metadata_filter.page_gte == 10

    chunk = Chunk(
        text="Deploy on Tuesdays.",
        metadata=ChunkMetadata(
            chunk_id="c1", source="doc.pdf", page=12, section="Deploy",
            chunk_index=0, char_start=0, char_end=18, doc_hash="b" * 64,
        ),
    )
    resp = RetrieveResponse(
        query=req.query,
        answer="Deploy on Tuesdays.",
        chunks=[ScoredChunk(chunk=chunk, score=0.9, retriever="rerank")],
        citations=[Citation.from_chunk(chunk, score=0.9)],
        trace=StageTrace(
            dense_count=20, sparse_count=20, fused_count=20,
            reranked_count=5, hyde_used=True,
        ),
    )
    decoded = RetrieveResponse.model_validate_json(resp.model_dump_json())
    assert decoded.trace.reranked_count == 5

def _schema_sse_events() -> None:
    from shared.schemas import (
        TokenEvent, CitationsEvent, TraceEvent, ErrorEvent, DoneEvent, StageTrace,
    )
    tok = TokenEvent(text="hello")
    assert tok.model_dump_json() == '{"type":"token","text":"hello"}'

    cites = CitationsEvent(citations=[])
    assert cites.type == "citations"

    trace = TraceEvent(trace=StageTrace(
        dense_count=1, sparse_count=1, fused_count=1, reranked_count=1, hyde_used=False,
    ))
    assert trace.type == "trace"

    err = ErrorEvent(message="boom", retryable=True)
    assert err.retryable is True

    done = DoneEvent()
    assert done.model_dump_json() == '{"type":"done"}'

def _schema_chat_roundtrip() -> None:
    from shared.schemas import ChatMessage, ChatRequest, SessionResponse
    from datetime import datetime
    msg = ChatMessage(role="user", content="hi")
    assert msg.role == "user"
    req = ChatRequest(session_id=None, message="What's the deploy policy?")
    assert req.session_id is None
    sess = SessionResponse(
        session_id="s1", messages=[msg],
        created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
    )
    decoded = SessionResponse.model_validate_json(sess.model_dump_json())
    assert decoded.messages[0].content == "hi"


# ─────────────────────────────────────────────────────────────
# 5. Logging
# ─────────────────────────────────────────────────────────────
def _logging_configure() -> None:
    from shared.logging.setup import configure_logging, get_logger
    configure_logging()
    configure_logging()  # idempotency check
    log = get_logger("smoke")
    log.debug("smoke_log_emitted", ok=True)


# ─────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────
def main() -> int:
    print("\n🧪 Smoke test: shared package\n" + "─" * 50)

    checks: list[tuple[str, object]] = [
        ("import: shared.config", _import_config),
        ("import: shared.providers", _import_providers),
        ("import: shared.schemas", _import_schemas),
        ("import: shared.logging", _import_logging),

        ("settings: paths resolve", _settings_paths_resolve),
        ("settings: env loaded + validated", _settings_env_loaded),
        ("settings: api key handling", _settings_api_key_handling),

        ("providers: constructible + Protocol conformance", _providers_constructible),

        ("schemas: Chunk round-trip + frozen metadata", _schema_chunk_roundtrip),
        ("schemas: Citation.from_chunk", _schema_citation_from_chunk),
        ("schemas: RetrieveRequest/Response round-trip", _schema_retrieve_roundtrip),
        ("schemas: SSE event shapes", _schema_sse_events),
        ("schemas: Chat round-trip", _schema_chat_roundtrip),

        ("logging: configure + log emit", _logging_configure),
    ]

    results = [check(label, fn) for label, fn in checks]

    print("─" * 50)
    passed = sum(results)
    total = len(results)
    if all(results):
        print(f"🎉 All {total} checks passed.\n")
        return 0
    print(f"⚠️  {passed}/{total} passed. Fix the failures above.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())