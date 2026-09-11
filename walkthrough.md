# Code Walkthrough

> Updated incrementally as each module lands. Each section: purpose,
> public functions, inputs/outputs, dependencies.

## File Map

| Path | Purpose | Entry point |
|------|---------|-------------|
| shared/shared/config/settings.py | Pydantic Settings, env loading | — |
| shared/shared/providers/base.py | `EmbeddingProvider`, `LLMProvider` Protocols | — |
| shared/shared/providers/openai_provider.py | OpenAI implementations | — |
| shared/shared/providers/factory.py | `get_embedding_provider()`, `get_llm_provider()` | — |
| shared/shared/schemas/*.py | Pydantic models for requests/responses | — |
| shared/shared/logging/setup.py | Structured logging config | — |
| services/ingestion/loader.py | pypdf wrapper | — |
| services/ingestion/chunker.py | RecursiveCharacterTextSplitter + metadata | — |
| services/ingestion/ingest.py | Load → chunk → embed → store | — |
| services/ingestion/app.py | FastAPI ingestion service | uvicorn services.ingestion.app:app |
| services/retrieval/hyde.py | Hypothetical doc generation | — |
| services/retrieval/bm25_index.py | Build/load BM25 + docstore | — |
| services/retrieval/dense.py | Chroma query wrapper | — |
| services/retrieval/sparse.py | BM25 query wrapper | — |
| services/retrieval/fusion.py | RRF | — |
| services/retrieval/rerank.py | Cross-encoder reranker | — |
| services/retrieval/generate.py | Prompt + streaming generation | — |
| services/retrieval/app.py | FastAPI retrieval service (SSE) | uvicorn services.retrieval.app:app |
| services/chat/session.py | In-memory session store | — |
| services/chat/orchestrator.py | Calls retrieval svc, manages history | — |
| services/chat/app.py | FastAPI chat service (SSE) | uvicorn services.chat.app:app |
| frontend/src/App.jsx | Chat UI root | vite |
| frontend/src/components/ChatWindow.jsx | Message list | — |
| frontend/src/components/MessageBubble.jsx | Single message | — |
| frontend/src/components/Citations.jsx | Source pills | — |
| frontend/src/components/InputBox.jsx | Input + send | — |
| frontend/src/components/TypingIndicator.jsx | Streaming indicator | — |
| frontend/src/lib/sse.js | SSE client wrapper | — |
| frontend/src/lib/api.js | Non-streaming fetch helpers | — |
| frontend/src/types/chat.js | JSDoc typedefs mirroring Pydantic | — |
| scripts/generate_eval_set.py | Synthetic Q/A via RAGAS TestsetGenerator | — |
| scripts/run_ablation.sh | 4-config ablation driver | — |
| evaluate.py | RAGAS harness (HTTP client of retrieval svc) | python evaluate.py |

## Detailed Sections


### shared/shared/config/settings.py

**Purpose:** Single source of truth for all runtime configuration across
ingestion, retrieval, chat, and evaluate.py. Loads env vars + `.env`,
validates on import, resolves paths relative to repo root (not CWD).

**Key objects:**
- `Settings` — Pydantic BaseSettings subclass, ~45 fields grouped by concern
- `settings` — module-level singleton (via `@lru_cache` `get_settings()`)
- `REPO_ROOT` — computed from `__file__`, used to make paths CWD-independent
- `require_openai_key()` — lazy validation; import never fails without a key

**Why lazy key validation:** Services should be importable and testable
without `OPENAI_API_KEY` present. Only code paths that actually call OpenAI
fail — and they fail with a clear message.

**Why paths, not env vars, for data locations:** `CHROMA_DIR` as an env
var invites drift across services. One computed root + relative paths
means all three services always agree.

**Ablation toggles (ADR-009):** `retrieval_dense_only`, `retrieval_hybrid`,
`retrieval_rerank`, `hyde_enabled` — read by `evaluate.py` via env vars to
run the 4-config ablation matrix without code edits.

**Dependencies:** `pydantic`, `pydantic-settings`. Nothing else.