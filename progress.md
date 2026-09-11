# Progress

## ✅ Done
- [x] Clarified document format (single PDF, 10–50 pages, text-native)
- [x] Confirmed OpenAI + provider abstraction requirement
- [x] Confirmed local cross-encoder reranker
- [x] Confirmed synthetic RAGAS eval set
- [x] Architecture, decisions, code-walkthrough, evaluation docs drafted

## ⚠️ Assumed (pending user override)
- [x] SSE for streaming (ADR-010)
- [x] Vite + React + Tailwind (ADR-011)
- [x] Local docker-compose only (ADR-017)

## 🚧 In Progress
- [ ] Awaiting user sign-off on assumed items before code

## ⏳ Pending — Shared
- [ ] shared/config/settings.py
- [ ] shared/providers/base.py (Protocols)
- [ ] shared/providers/openai_provider.py
- [ ] shared/providers/factory.py
- [ ] shared/schemas/ (ingest, retrieve, chat, citations)
- [ ] shared/logging/setup.py

## ⏳ Pending — Ingestion Service
- [ ] services/ingestion/ingest.py
- [ ] services/ingestion/app.py
- [ ] services/ingestion/__init__.py

## ⏳ Pending — Retrieval Service
- [ ] services/retrieval/hyde.py
- [ ] services/retrieval/bm25_index.py
- [ ] services/retrieval/retrieval.py
- [ ] services/retrieval/rerank.py
- [ ] services/retrieval/generate.py
- [ ] services/retrieval/app.py

## ⏳ Pending — Chat Service
- [ ] services/chat/session.py
- [ ] services/chat/app.py

## ⏳ Pending — Frontend
- [ ] Vite + React + TS + Tailwind scaffold
- [ ] App.tsx, ChatWindow, MessageBubble, InputBox, Citations
- [ ] lib/sse.ts
- [ ] .env with VITE_CHAT_URL

## ⏳ Pending — Infra & Tooling
- [ ] docker-compose.yml
- [ ] Makefile (dev, ingest, eval, test)
- [ ] .env.example
- [ ] pyproject.toml / requirements per service
- [ ] README.md

## ⏳ Pending — Evaluation
- [ ] evaluate.py (RAGAS harness)
- [ ] Synthetic eval set generation script
- [ ] Ablation run (dense-only / +BM25+RRF / +rerank / +HyDE)
- [ ] Results table filled in evaluation.md

## 🚫 Blocked
- Nothing blocked. Ready to start `/shared` on your sign-off.