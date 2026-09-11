# Progress

## ✅ Done
- [x] Clarified document format (single PDF, 10–50 pages, text-native)
- [x] Confirmed OpenAI + provider abstraction requirement
- [x] Confirmed local cross-encoder reranker
- [x] Confirmed synthetic RAGAS eval set
- [x] Confirmed frontend in JS (not TS)
- [x] Architecture, decisions, code-walkthrough, evaluation docs drafted
- [x] All 19 ADRs accepted
- [x] Folder tree approved

## ✅ Done (continued)
- [x] shared/pyproject.toml
- [x] shared/shared/config/settings.py
- [x] PDF confirmed text-selectable
- [x] shared/shared/providers/base.py + __init__.py
- [x] Embedding batching decided (BATCH_SIZE=500, private _embed_batch)
- [x] shared/shared/providers/openai_provider.py
- [x] Schema dependency DAG decided (chunk.py as domain primitive)
- [x] Schema invariant locked: chunk.py stays pure (no query/retrieval/transport concepts)
- [x] shared/shared/logging/setup.py

## 📌 Milestone
`shared/` is a complete, installable, testable package.
Next: ingestion service.

## ✅ Done — SHARED PACKAGE COMPLETE (14/15 checks + 1 skip)
- [x] shared/pyproject.toml (rag-shared 0.1.0, ollama dep added)
- [x] shared/shared/config/ (settings.py with Ollama defaults, __init__.py)
- [x] shared/shared/providers/ (base.py, openai_provider.py, ollama_provider.py, factory.py, __init__.py)
- [x] shared/shared/schemas/ (chunk, citations, ingest, retrieve, chat, __init__.py)
- [x] shared/shared/logging/ (setup.py, __init__.py)
- [x] ADR-021, ADR-022 logged
- [x] Smoke test passing
- [x] Live Ollama round-trip verified (nomic-embed-text + llama3.2)


## ✅ Done (continued)
- [x] services/ingestion/pyproject.toml (Layout A)
- [x] services/ingestion/ingestion/loader.py (verified against real PDF: N pages, M chars)
- [x] rag-ingestion installed editable
- [x] Cleaned up stale placeholder files
- [x] Removed stale shared/shared.egg-info
- [x] services/ingestion/chunker.py
- [x] Chroma mode decided: PersistentClient (embedded)
- [x] BM25 storage decided: bm25.pkl + docstore.json (human-readable)
- [x] Consistency strategy decided: best-effort + check_consistency() at startup
- [x] services/ingestion/ingestion/ingest.py — end-to-end ingest works
- [x] 36 chunks in Chroma + BM25, consistency check ok
- [x] Idempotency: sentinel row + doc_hash check
- [x] Chroma telemetry log silenced
- [x] GET /collections fixed for Chroma 0.6.x (list_collections returns names)

## 🐛 Known Issues (non-blocking)
- First-embed warmup ~36s (measure second run); acceptable for demo, revisit if consistent


## ✅ Done — INGESTION SERVICE COMPLETE
- [x] services/ingestion/pyproject.toml (Layout A)
- [x] services/ingestion/ingestion/loader.py — verified: 7 pages, 21,731 chars
- [x] services/ingestion/ingestion/chunker.py — verified: 36 chunks
- [x] services/ingestion/ingestion/ingest.py — Chroma + BM25, sentinel, idempotency
- [x] services/ingestion/ingestion/app.py — /health, /ingest, /collections
- [x] services/ingestion/Dockerfile + .dockerignore
- [x] Ollama embeddings: 36s cold, 1.08s warm — no latency problem
- [x] Chroma 0.6.x compatibility fix (list_collections returns names)

## 🚧 In Progress — Retrieval Service Batch 2 (files 6-9)
- [ ] services/retrieval/retrieval/rerank.py
- [ ] services/retrieval/retrieval/hyde.py
- [ ] services/retrieval/retrieval/generate.py
- [ ] services/retrieval/retrieval/app.py (with POST /reload stub)
- [ ] services/retrieval/Dockerfile + .dockerignore

## ✅ Done (continued) — Retrieval Service Batch 1
- [x] services/retrieval/pyproject.toml
- [x] services/retrieval/retrieval/bm25_index.py (36 chunks loaded)
- [x] services/retrieval/retrieval/dense.py (semantic search verified)
- [x] services/retrieval/retrieval/sparse.py (BM25 verified)
- [x] services/retrieval/retrieval/fusion.py (RRF verified — consensus ranking working)

## ✅ Done (continued) — Batch 2 decisions
- [x] services/retrieval/pyproject.toml
- [x] services/retrieval/retrieval/bm25_index.py
- [x] services/retrieval/retrieval/dense.py
- [x] services/retrieval/retrieval/sparse.py
- [x] services/retrieval/retrieval/fusion.py (RRF verified)
- [x] services/retrieval/retrieval/rerank.py (cross-encoder verified)
- [x] services/retrieval/retrieval/hyde.py (query rewrite verified)
- [x] services/retrieval/retrieval/generate.py (SSE streaming verified)
- [x] services/retrieval/retrieval/app.py (/health, /retrieve, /retrieve/sync, /reload)
- [x] services/retrieval/Dockerfile + .dockerignore
- [x] End-to-end: query → HyDE → dense+sparse → RRF → rerank → streamed answer + citations
- [x] Verified: "What is the deployment policy?" returns correct, cited answer

- [ ] services/chat/ — starting now

## ⏳ Pending — Chat Service
- [ ] services/chat/pyproject.toml + Dockerfile + .dockerignore
- [ ] services/chat/session.py
- [ ] services/chat/orchestrator.py
- [ ] services/chat/app.py
- [ ] services/chat/tests/

## ⏳ Pending — Frontend (JS)
- [ ] Vite + React + JS + Tailwind scaffold
- [ ] App.jsx, ChatWindow, MessageBubble, InputBox, Citations, TypingIndicator
- [ ] lib/sse.js, lib/api.js, types/chat.js
- [ ] .env (VITE_CHAT_URL)

## ⏳ Pending — Infra & Tooling
- [ ] docker-compose.yml
- [ ] Makefile (dev, ingest, eval, ablation, test)
- [ ] .env.example
- [ ] .gitignore
- [ ] README.md
- [ ] .github/workflows/ci.yml (ruff + pytest + eslint + vite build)

## ⏳ Pending — Evaluation
- [ ] scripts/generate_eval_set.py
- [ ] evaluate.py (RAGAS harness)
- [ ] scripts/run_ablation.sh
- [ ] Ablation run → results filled in evaluation.md

## 🚫 Blocked
- Nothing blocked.

## 🔄 Changed
- [x] Switched default provider to Ollama (llama3.2 + nomic-embed-text)
- [x] Amended ADR-003, added ADR-022

## ⏳ Pending — Ollama provider
- [ ] providers/ollama_provider.py
- [ ] Update providers/factory.py (add "ollama" branch)
- [ ] Update providers/__init__.py (export)
- [ ] Update settings.py (defaults + ollama_url)
- [ ] Update shared/pyproject.toml (add `ollama` dep)
- [ ] Re-run smoke test