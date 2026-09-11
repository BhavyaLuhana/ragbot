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

## 🚧 In Progress
- [ ] shared/shared/providers/base.py

## ✅ Done (continued)
- [x] shared/pyproject.toml
- [x] shared/shared/config/settings.py
- [x] PDF confirmed text-selectable

## ⏳ Pending — Shared
- [ ] shared/pyproject.toml
- [ ] shared/shared/config/settings.py
- [ ] shared/shared/providers/base.py (Protocols)
- [ ] shared/shared/providers/openai_provider.py
- [ ] shared/shared/providers/factory.py
- [ ] shared/shared/schemas/ (ingest, retrieve, chat, citations)
- [ ] shared/shared/logging/setup.py
- [ ] shared/tests/

## ⏳ Pending — Ingestion Service
- [ ] services/ingestion/pyproject.toml + Dockerfile + .dockerignore
- [ ] services/ingestion/loader.py
- [ ] services/ingestion/chunker.py
- [ ] services/ingestion/ingest.py
- [ ] services/ingestion/app.py
- [ ] services/ingestion/tests/

## ⏳ Pending — Retrieval Service
- [ ] services/retrieval/pyproject.toml + Dockerfile + .dockerignore
- [ ] services/retrieval/hyde.py
- [ ] services/retrieval/bm25_index.py
- [ ] services/retrieval/dense.py
- [ ] services/retrieval/sparse.py
- [ ] services/retrieval/fusion.py
- [ ] services/retrieval/rerank.py
- [ ] services/retrieval/generate.py
- [ ] services/retrieval/app.py
- [ ] services/retrieval/tests/

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