# Architecture

## 1. System Overview
A microservices RAG system over a single private PDF, with a React chat
frontend, FastAPI backends, ChromaDB (dense) + BM25 (sparse) hybrid
retrieval, Reciprocal Rank Fusion, a local cross-encoder reranker, and
HyDE query rewriting. OpenAI provides embeddings + generation behind a
provider abstraction. Evaluated with RAGAS on a synthetic eval set.

## 2. Repository Layout

/frontend                 React + Vite + Tailwind chat UI (SSE consumer)
/services
  /ingestion              FastAPI: load → clean → chunk → embed → store
  /retrieval              FastAPI: query → HyDE → hybrid → RRF → rerank → generate (SSE)
  /chat                   FastAPI: conversation state, multi-turn, calls retrieval
/shared
  /config                 Pydantic Settings (env-driven)
  /providers              LLM + embedding provider abstraction (OpenAI default)
  /schemas                Pydantic request/response models shared across services
  /logging                Structured logging config
/data
  /raw                    Source PDF(s)
  /chroma                 ChromaDB persistence volume
  /bm25                   Pickled BM25 index + doc store
/evaluate.py              RAGAS harness (HTTP client of retrieval svc)
/docker-compose.yml       Orchestrates services + frontend
/Makefile                 dev, ingest, eval shortcuts
/.env.example             All required env vars

## 3. Corpus Assumptions
- Single PDF, 10–50 pages, text-native (no OCR)
- English
- Fits comfortably in memory; no sharding needed

## 4. Service Responsibilities

| Service    | Owns                                              | Talks to                                    | Exposes                                        |
|------------|---------------------------------------------------|---------------------------------------------|------------------------------------------------|
| ingestion  | Load PDF, chunk+metadata, embed, upsert Chroma + BM25 | OpenAI, Chroma, disk                    | POST /ingest, GET /health, GET /collections    |
| retrieval  | HyDE, dense+sparse search, RRF, rerank, generation | Chroma, BM25, OpenAI, cross-encoder         | POST /retrieve (SSE), POST /retrieve/sync      |
| chat       | Conversation history, session store, orchestration | retrieval                                   | POST /chat (SSE), GET /sessions/{id}           |
| frontend   | Chat UI, SSE consumer, citation rendering         | chat                                        | —                                              |

## 5. Data Flow

### 5.1 Ingestion (admin-triggered, offline)
```mermaid
flowchart LR
  A[Admin] -->|POST /ingest| I[ingestion svc]
  I --> L[pypdf Loader]
  L --> C[RecursiveCharacterTextSplitter + metadata]
  C --> E[OpenAI text-embedding-3-small]
  E --> CH[(ChromaDB persistent)]
  C --> BM[(BM25Okapi pickle + doc store)]



  