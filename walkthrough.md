# Code Walkthrough

> Updated incrementally as each module lands. Each section: purpose,
> public functions, inputs/outputs, dependencies.

## File Map

| Path | Purpose | Entry point |
|------|---------|-------------|
| shared/config/settings.py | Pydantic Settings, env loading | — |
| shared/providers/base.py | `EmbeddingProvider`, `LLMProvider` Protocols | — |
| shared/providers/openai_provider.py | OpenAI implementations | — |
| shared/providers/factory.py | `get_embedding_provider()`, `get_llm_provider()` | — |
| shared/schemas/*.py | Pydantic models for requests/responses | — |
| services/ingestion/ingest.py | Load → chunk → embed → store | — |
| services/ingestion/app.py | FastAPI ingestion service | uvicorn services.ingestion.app:app |
| services/retrieval/hyde.py | Hypothetical doc generation | — |
| services/retrieval/bm25_index.py | Build/load BM25 + doc store | — |
| services/retrieval/retrieval.py | Dense + sparse + RRF | — |
| services/retrieval/rerank.py | Cross-encoder reranker | — |
| services/retrieval/generate.py | Prompt + streaming generation | — |
| services/retrieval/app.py | FastAPI retrieval service (SSE) | uvicorn services.retrieval.app:app |
| services/chat/session.py | In-memory session store | — |
| services/chat/app.py | FastAPI chat service (SSE) | uvicorn services.chat.app:app |
| frontend/src/App.tsx | Chat UI root | vite |
| frontend/src/components/ChatWindow.tsx | Message list | — |
| frontend/src/components/MessageBubble.tsx | Single message | — |
| frontend/src/components/Citations.tsx | Source pills | — |
| frontend/src/components/InputBox.tsx | Input + send | — |
| frontend/src/lib/sse.ts | SSE client wrapper | — |
| evaluate.py | RAGAS harness (HTTP client of retrieval svc) | python evaluate.py |

## Detailed Sections
_(populated as each file is written)_

### shared/config/settings.py
_TBD_

### shared/providers/base.py
_TBD_

... (one section per file)