
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
Qdrant (great, but extra service), FAISS (no metadata filter).
**Pros:** Zero infra, metadata filtering built-in, persisted to disk,
LangChain integration, easy to swap later.
**Cons:** Not production-scale, single-node. Acceptable for demo.
**Status:** Accepted.

## ADR-002: RecursiveCharacterTextSplitter over fixed-size / semantic
**Context:** 10–50 page PDF; want coherent chunks with overlap.
**Decision:** RecursiveCharacterTextSplitter, chunk_size=800, overlap=150,
separators=["\n\n", "\n", ". ", " ", ""].
**Alternatives:** Fixed-size (breaks mid-sentence), semantic chunking
(extra embedding calls, latency), token-based (minor benefit at this scale).
**Pros:** Respects paragraph/sentence boundaries, standard, tunable.
**Cons:** Not perfect at tables/code (PDF is prose, fine).
**Status:** Accepted.

## ADR-003: Provider selection — Ollama primary, OpenAI alternative
**Context:** Need embeddings + generation. Original draft assumed OpenAI
only, but we want the default to run with zero API keys during development.
The provider abstraction (ADR-016) was designed for exactly this swap.

**Decision:**
- **Default:** Ollama, local.
  - LLM: `llama3.2`
  - Embeddings: `nomic-embed-text` (768d)
- **Alternative:** OpenAI, available by changing one env var.
  - LLM: `gpt-4o-mini`
  - Embeddings: `text-embedding-3-small` (1536d)
  - Kept implemented so the abstraction is demonstrably real (ADR-022).

**Alternatives considered:**
- OpenAI-only (rejected: needs key, costs money, network dependency)
- Local sentence-transformers embeddings + separate local LLM
  (rejected: Ollama wraps both behind one consistent interface)
- vLLM / llama.cpp direct (rejected: Ollama is batteries-included)

**Pros (Ollama):** No key, offline-capable, private, free, deterministic
at `temperature=0`, easy to demo, single-tool lifecycle for both LLM and
embeddings.

**Cons (Ollama):** Slower on cold start; requires Ollama installed and
models pulled (~2–5GB); `nomic-embed-text` is 768d — different from
OpenAI's 1536d, which changes the Chroma collection dimensionality. This
is handled by config (`EMBEDDING_DIM`), not code, but must be set
consistently across ingestion and retrieval.

**Status:** Accepted. Supersedes the earlier OpenAI-only framing of ADR-003.

## ADR-004: Hybrid (dense + BM25) over dense-only
**Context:** Dense misses exact terms (names, IDs, rare tokens); BM25 misses paraphrases.
**Decision:** Run both, fuse with RRF.
**Alternatives:** Dense-only (fails on exact-match), BM25-only (fails on semantic).
**Pros:** Robust across query types; measurable recall lift in ablations.
**Cons:** Two indexes to keep in sync (mitigated: ingestion writes both atomically).
**Status:** Accepted.

## ADR-005: RRF over weighted-score fusion
**Context:** Dense (cosine) and BM25 (unbounded) scores not comparable.
**Decision:** Reciprocal Rank Fusion: score(d) = Σ 1/(k + rank_i(d)), k=60.
**Alternatives:** Normalize + weighted sum (brittle), CombSUM (same issue).
**Pros:** Scale-free, no tuning, well-cited (Cormack et al. 2009), robust.
**Cons:** Ignores score magnitude — acceptable.
**Status:** Accepted.

## ADR-006: Local cross-encoder/ms-marco-MiniLM-L-6-v2 over Cohere Rerank
**Context:** Rerank top-20 → top-5 for the LLM prompt.
**Decision:** Local sentence-transformers cross-encoder.
**Alternatives:** Cohere Rerank (API cost, extra provider), bge-reranker-base
(larger), no rerank (worse context precision).
**Pros:** Free, ~90MB, CPU-fast, no extra API key.
**Cons:** Cold start ~2s (mitigated: warm at service startup).
**Status:** Accepted.

## ADR-007: HyDE enabled by default, toggleable
**Context:** Short user queries retrieve poorly against doc-style embeddings.
**Decision:** Generate a hypothetical answer with GPT-4o-mini, embed it,
use for dense retrieval. Sparse retrieval uses raw query.
**Alternatives:** Raw query only (baseline), multi-query (more latency),
step-back (complementary, not a replacement).
**Pros:** Recall lift on vague/short queries.
**Cons:** +1 LLM call (~300–500ms); hallucination risk. Mitigated: fallback
to raw query on failure; env toggle.
**Status:** Accepted (default ON, `HYDE_ENABLED` toggle).

## ADR-008: Chunk metadata schema
**Context:** Citations need page + section; dedup needs hash.
**Decision:** See architecture.md §7.
**Alternatives:** Minimal (source + page) — insufficient for citations UX.
**Pros:** Rich citations, doc-level dedup, Chroma `where` filters.
**Cons:** Larger index (negligible).
**Status:** Accepted.

## ADR-009: RAGAS with synthetic eval set
**Context:** No ground-truth Q/A; need measurable quality.
**Decision:** Generate 25 synthetic Q/A pairs with GPT-4o-mini via RAGAS
`TestsetGenerator`; evaluate Faithfulness, Answer Relevancy, Context Recall,
Context Precision.
**Alternatives:** Hand-write eval (slow, biased), no eval (unacceptable).
**Pros:** Standard, automated, produces the ablation table.
**Cons:** Synthetic questions can be "too easy"; mitigated by mixing in
multi-hop + unanswerable questions manually.
**Status:** Accepted.

## ADR-010: SSE over WebSocket for streaming
**Context:** Chat answers stream token-by-token to React.
**Decision:** Server-Sent Events via FastAPI StreamingResponse.
**Alternatives:** WebSocket (bidirectional, unneeded), long-polling (worse UX).
**Pros:** Native EventSource, HTTP/2-friendly, no extra client lib, curl-debuggable.
**Cons:** Unidirectional. Mitigation: separate cancel endpoint if needed (out of scope).
**Status:** Accepted.

## ADR-011: Vite + React + Tailwind over Next.js
**Context:** Standalone chat UI consuming a separate FastAPI backend.
**Decision:** Vite + React (JavaScript) + Tailwind CSS.
**Alternatives:** Next.js (SSR not needed, blurs boundaries), CRA (deprecated).
**Pros:** Fast HMR, tiny config, clean separation, Tailwind = fast UI iteration.
**Cons:** No SSR (irrelevant for this app).
**Status:** Accepted.

## ADR-012: REST for inter-service comms (queue deferred)
**Context:** chat → retrieval → ingestion need to talk.
**Decision:** Synchronous REST over HTTP (httpx async). Ingestion is an
admin-triggered REST call.
**Alternatives:** RabbitMQ/Kafka (overkill), gRPC (schema + tooling overhead).
**Pros:** Zero infra, curl-debuggable, matches request/response semantics.
**Cons:** No backpressure / retry queue / fan-out.
**In prod:** Ingestion of large corpora → RabbitMQ + worker pool. Retrieval
stays REST.
**Status:** Accepted (with prod note).

## ADR-013: Co-hosted services, separate entrypoints
**Context:** Microservices ops overhead vs monolith simplicity.
**Decision:** Each service is its own FastAPI app; docker-compose runs all
three; `make dev` runs them locally in parallel.
**Alternatives:** True monolith (loses interview story), k8s (absurd).
**Pros:** Real service boundaries; one-command demo.
**Cons:** Slight dev tooling duplication.
**Status:** Accepted.

## ADR-014: CORS via FastAPI CORSMiddleware
**Context:** React (localhost:5173) → FastAPI (localhost:8000-8002).
**Decision:** CORSMiddleware on chat + retrieval; `allow_origins` from
`FRONTEND_ORIGIN` env (default http://localhost:5173). For SSE, set
`expose_headers=["Content-Type"]`, disable proxy buffering.
**Alternatives:** Nginx reverse proxy (overkill locally).
**Pros:** Simple, env-driven, prod-lockdown is a one-line change.
**Cons:** Must restrict origins in prod (documented).
**Status:** Accepted.

## ADR-015: Monorepo with shared package
**Context:** Shared Pydantic schemas + config across 3 services.
**Decision:** Single repo, `/shared` imported as a local editable package.
**Alternatives:** Polyrepo (overkill), copy-paste (drift).
**Pros:** Atomic commits, no schema drift, one CI.
**Cons:** Coupling — acceptable at this scale.
**Status:** Accepted.

## ADR-016: Provider abstraction layer over OpenAI SDK
**Context:** Swapping providers must be a config change, not a code change.
**Decision:** `shared/providers/` exposes `EmbeddingProvider` and
`LLMProvider` Protocols. `OpenAIProvider` implements both. Config selects
via `EMBEDDING_PROVIDER=openai` / `LLM_PROVIDER=openai`.
**Alternatives:** Direct OpenAI SDK calls (violates requirement).
**Pros:** Meets requirement; cleaner tests (inject fakes); future-proof.
**Cons:** One extra indirection layer.
**Status:** Accepted.

## ADR-017: Deployment target = local docker-compose
**Context:** Demo needs to run with one command.
**Decision:** `docker-compose up` launches ingestion, retrieval, chat, frontend.
**Alternatives:** Fly.io / Railway (extra scope).
**Pros:** Fully reproducible, zero cloud cost, works offline post-ingest.
**Cons:** Not publicly demoable. Mitigation: README + screenshots.
**Status:** Accepted.

## ADR-018: `shared/` as an installable editable package
**Context:** Three services need the same config, Pydantic schemas, and
provider abstractions.
**Decision:** `shared/` is its own package with its own `pyproject.toml`.
Each service declares it as a dependency and installs it with
`pip install -e ./shared` (dev) or via Dockerfile.
**Alternatives:**
  - Copy-paste → drift, no single source of truth. Rejected.
  - `PYTHONPATH=./shared` hack → breaks IDE nav, type checkers, wheel builds. Rejected.
  - Pants/Bazel → massive overkill. Rejected.
**Pros:** Single source of truth; works with mypy, ruff, IDE jump-to-def;
no import hacks; services stay independently deployable.
**Cons:** One extra install step per Dockerfile; editable installs can be
surprising in CI (mitigated by non-editable install in CI).
**Status:** Accepted.

## ADR-019: Plain JavaScript over TypeScript for the frontend
**Context:** User preference — React in JS, not TS.
**Decision:** Frontend uses `.jsx` / `.js` with JSDoc `@typedef` blocks in
`src/types/chat.js` for editor autocomplete on API shapes.
**Alternatives:** TypeScript (rejected by user), Flow (dead ecosystem).
**Pros:** Lower friction, no build-time type step, faster iteration; JSDoc
still gives IDE hints.
**Cons:** No compile-time contract enforcement between frontend and
Pydantic schemas. Mitigated by: backend is the source of truth,
`shared/schemas/` is the documented contract, runtime validation can be
added later if drift becomes real.
**Status:** Accepted (user constraint).

## ADR-021: Auto-select log format by environment
**Context:** Local dev wants readable colorized logs; CI/prod want
machine-parseable JSON for aggregators (Loki, Datadog, CloudWatch).
**Decision:** `configure_logging()` picks the renderer from
`settings.environment` (`local` → ConsoleRenderer, `ci`/`prod` →
JSONRenderer). `LOG_JSON` env var overrides if set.
**Alternatives:** Manual flag (drift, easy to forget in one service);
always JSON (painful in dev); always pretty (useless in prod).
**Pros:** Correct by default; one override if needed; no per-service config.
**Cons:** Log shape differs between environments — documented inline in
`logging/setup.py` so no one is surprised.
**Status:** Accepted.

## ADR-022: Keep OpenAI provider alongside Ollama
**Context:** Ollama is now the default. Should we delete
`openai_provider.py` and drop the `openai` dependency?

**Decision:** No. Keep both. `EMBEDDING_PROVIDER` and `LLM_PROVIDER` env
vars select at runtime. Both providers are first-class.

**Alternatives:** Delete the OpenAI provider (simpler codebase, fewer deps).

**Pros (keep both):**
- The provider abstraction (ADR-016) is *demonstrably* real — a reviewer
  can flip an env var and watch the pipeline run against a different
  backend. A README claim alone is resume-driven; two working providers
  is proof.
- Fallback if Ollama isn't installed on a reviewer's machine.
- Lets us use OpenAI's stronger judge later for RAGAS evaluation without
  paying for the whole pipeline.

**Cons:** Two code paths to maintain; `openai` remains a dependency of
`shared/` even when unused.

**Status:** Accepted.