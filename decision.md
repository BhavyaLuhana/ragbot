
---

## 📄 `decisions.md`

```markdown
# Architectural Decisions (ADR Log)

Format: Context → Decision → Alternatives → Pros/Cons → Status.

---

## ADR-001: ChromaDB over Pinecone / Weaviate / Qdrant
**Context:** Need a vector store for ~10–50 pages (~200–500 chunks). Local dev.
**Decision:** ChromaDB in persistent local mode.
**Alternatives:** Pinecone (managed, cost, network), Weaviate (heavier ops),
Qdrant (great, but Rust binary + extra service), FAISS (no metadata filter).
**Pros:** Zero infra, metadata filtering built-in, persisted to disk, LangChain
integration, easy to swap later.
**Cons:** Not production-scale, single-node. Acceptable for demo.
**Status:** Accepted.

## ADR-002: RecursiveCharacterTextSplitter over fixed-size / semantic
**Context:** 10–50 page PDF, want coherent chunks with overlap.
**Decision:** RecursiveCharacterTextSplitter, chunk_size=800, overlap=150,
separators=["\n\n", "\n", ". ", " ", ""].
**Alternatives:** Fixed-size (breaks mid-sentence), semantic chunking
(extra embedding calls + latency, overkill here), token-based (harder to
reason about, minor benefit at this scale).
**Pros:** Respects paragraph/sentence boundaries, standard, tunable.
**Cons:** Not perfect at tables/code (PDF is prose, fine).
**Status:** Accepted.

## ADR-003: OpenAI text-embedding-3-small + GPT-4o-mini
**Context:** Need embeddings + generation; provider abstraction required (ADR-016).
**Decision:** `text-embedding-3-small` (1536d) + `gpt-4o-mini`.
**Alternatives:** -large embedding (5× cost, marginal gain at this scale),
GPT-4o (overkill cost), local embeddings (slower cold start, lower quality).
**Pros:** Cheap, fast, high quality, stable API.
**Cons:** Network dependency, data leaves machine (acceptable — non-sensitive demo).
**Status:** Accepted.

## ADR-004: Hybrid (dense + BM25) over dense-only
**Context:** Dense misses exact terms (names, IDs, rare tokens); BM25 misses
paraphrases.
**Decision:** Run both, fuse with RRF.
**Alternatives:** Dense-only (fails on exact-match queries), BM25-only
(fails on semantic queries).
**Pros:** Robust across query types, measurable recall lift in ablations.
**Cons:** Two indexes to keep in sync (mitigated: ingestion writes both atomically).
**Status:** Accepted.

## ADR-005: RRF over weighted-score fusion
**Context:** Dense (cosine) and BM25 (unbounded) scores are not comparable.
**Decision:** Reciprocal Rank Fusion: score(d) = Σ 1/(k + rank_i(d)), k=60.
**Alternatives:** Normalize + weighted sum (needs per-query calibration,
brittle), CombSUM (similar issue).
**Pros:** Scale-free, no tuning, well-cited (Cormack et al. 2009), robust.
**Cons:** Ignores score magnitude — acceptable tradeoff.
**Status:** Accepted.

## ADR-006: Local cross-encoder/ms-marco-MiniLM-L-6-v2 over Cohere Rerank
**Context:** Need to rerank top-20 → top-5 for the LLM prompt.
**Decision:** Local sentence-transformers cross-encoder.
**Alternatives:** Cohere Rerank (API cost, extra provider), bge-reranker-base
(similar, larger), no rerank (measurably worse context precision).
**Pros:** Free, ~90MB, CPU-fast at this scale, no extra API key.
**Cons:** Cold start ~2s on first call (mitigated: warm at service startup).
**Status:** Accepted.

## ADR-007: HyDE enabled by default, toggleable
**Context:** User queries are short; hypothetical doc embeddings often
retrieve better than raw queries.
**Decision:** Generate a hypothetical answer with GPT-4o-mini, embed it,
use for dense retrieval. Sparse retrieval uses raw query.
**Alternatives:** Raw query only (baseline), multi-query (more latency, more
API cost), step-back prompting (complementary, not a replacement).
**Pros:** Recall lift on vague/short queries, well-cited technique.
**Cons:** +1 LLM call latency (~300–500ms); can hallucinate away from intent.
Mitigated: fallback to raw query if HyDE call fails; toggle in config.
**Status:** Accepted (default ON, env-toggleable).

## ADR-008: Chunk metadata schema
**Context:** Citations need page + section; dedup needs hash.
**Decision:** See architecture.md §7.
**Alternatives:** Minimal (source + page only) — insufficient for citations UX.
**Pros:** Enables rich citations, doc-level dedup, and Chroma `where` filters.
**Cons:** Slightly larger index (negligible).
**Status:** Accepted.

## ADR-009: RAGAS with synthetic eval set
**Context:** No ground-truth Q/A. Need measurable retrieval/generation quality.
**Decision:** Generate 25 synthetic Q/A pairs from the PDF with GPT-4o-mini
(via RAGAS `TestsetGenerator`), evaluate Faithfulness, Answer Relevancy,
Context Recall, Context Precision.
**Alternatives:** Hand-write eval (slow, biased), no eval (unacceptable for
an interview portfolio piece).
**Pros:** Standard, automated, produces the ablation table recruiters love.
**Cons:** Synthetic questions can be "too easy" (grounded in single chunks);
mitigated by mixing in multi-hop + unanswerable questions manually.
**Status:** Accepted.

## ADR-010: SSE over WebSocket for streaming
**Context:** Chat answers stream token-by-token to React.
**Decision:** Server-Sent Events via FastAPI StreamingResponse.
**Alternatives:** WebSocket (bidirectional, unneeded), long-polling (worse UX).
**Pros:** Native EventSource in browser, HTTP/2-friendly, no extra client lib,
trivial to debug with curl.
**Cons:** Unidirectional. Mitigation: separate POST /chat/{id}/cancel endpoint
if we ever need interruption (out of scope).
**Status:** Accepted. `[ASSUMED — confirm or override]`

## ADR-011: Vite + React + Tailwind over Next.js
**Context:** Standalone chat UI consuming a separate FastAPI backend.
**Decision:** Vite + React + TypeScript + Tailwind.
**Alternatives:** Next.js (SSR not needed, blurs backend/frontend boundary),
CRA (deprecated).
**Pros:** Fast HMR, tiny config, clean microservice separation, Tailwind =
fast UI iteration.
**Cons:** No SSR (irrelevant for a chat app behind a login-less demo).
**Status:** Accepted. `[ASSUMED — confirm or override]`

## ADR-012: REST for inter-service comms (queue deferred)
**Context:** chat → retrieval → ingestion need to talk.
**Decision:** Synchronous REST over HTTP (httpx async). Ingestion is an
admin-triggered REST call.
**Alternatives:** RabbitMQ/Kafka (overkill at this scale), gRPC (faster but
schema + tooling overhead not worth it here).
**Pros:** Zero infra, curl-debuggable, matches request/response semantics.
**Cons:** No backpressure / retry queue / fan-out.
**In prod:** Ingestion of large corpora → RabbitMQ + worker pool. Retrieval
stays REST (latency-critical, synchronous).
**Status:** Accepted (with prod note).

## ADR-013: Co-hosted services, separate entrypoints
**Context:** Microservices ops overhead vs monolith simplicity.
**Decision:** Each service is its own FastAPI app; docker-compose runs all
three; `make dev` runs them in parallel locally.
**Alternatives:** True monolith (loses interview story), k8s (absurd for demo).
**Pros:** Real service boundaries for the portfolio narrative; one-command demo.
**Cons:** Slight dev tooling duplication.
**Status:** Accepted.

## ADR-014: CORS via FastAPI CORSMiddleware
**Context:** React (localhost:5173) → FastAPI (localhost:8000-8002).
**Decision:** CORSMiddleware on chat + retrieval, `allow_origins` from
`FRONTEND_ORIGIN` env (default http://localhost:5173). For SSE, set
`expose_headers=["Content-Type"]`, disable proxy buffering.
**Alternatives:** Nginx reverse proxy (overkill locally).
**Pros:** Simple, env-driven, prod-lockdown is a one-line change.
**Cons:** Must remember to restrict origins in prod (documented).
**Status:** Accepted.

## ADR-015: Monorepo with shared package
**Context:** Shared Pydantic schemas + config across 3 services.
**Decision:** Single repo, `/shared` imported as a local editable package
(`pip install -e ./shared`).
**Alternatives:** Polyrepo (overkill), copy-paste (drift).
**Pros:** Atomic commits, no schema drift, one CI.
**Cons:** Coupling — acceptable at this scale.
**Status:** Accepted.

## ADR-016: Provider abstraction layer over OpenAI SDK
**Context:** Swapping providers must be a config change, not a code change.
**Decision:** `shared/providers/` exposes `EmbeddingProvider` and
`LLMProvider` Protocols. `OpenAIProvider` implements both. Config selects
via `EMBEDDING_PROVIDER=openai` / `LLM_PROVIDER=openai`. New providers =
new class + env value.
**Alternatives:** Direct OpenAI SDK calls (violates stated requirement).
**Pros:** Meets requirement, cleaner tests (can inject fake providers),
future-proof for Anthropic/Cohere/local Ollama.
**Cons:** One extra indirection layer (worth it).
**Status:** Accepted.

## ADR-017: Deployment target = local docker-compose
**Context:** Demo needs to run with one command.
**Decision:** `docker-compose up` launches ingestion, retrieval, chat, frontend.
Local-only; no cloud deploy.
**Alternatives:** Fly.io / Railway (extra scope, not needed for interviews).
**Pros:** Fully reproducible, zero cloud cost, works offline (post-ingest).
**Cons:** Not publicly demoable. Mitigation: README with screenshots + a
short Loom-style recording plan.
**Status:** Accepted. `[ASSUMED — confirm or override]`