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


### shared/shared/providers/base.py

**Purpose:** Defines the two Protocols (`EmbeddingProvider`, `LLMProvider`)
that every concrete provider satisfies, plus a shared `ProviderError`.
Services depend on these Protocols, never on `openai` directly.

**Key design points:**

1. **`Protocol` + `@runtime_checkable` over ABC.** Structural typing means
   a third-party SDK wrapper or a test fake can satisfy the shape without
   inheriting from us. `runtime_checkable` lets `isinstance()` checks work
   in factory validation.

2. **`stream()` yields raw strings, not structured events.**
   Transport formatting is not the provider's job — the SSE layer in
   `retrieval/generate.py` wraps tokens into `{"type": "token", ...}` and
   emits the final `{"type": "done"}`. This keeps providers portable
   (OpenAI, Anthropic, Ollama all yield plain tokens natively) and makes
   the Protocol trivially unit-testable (assert `list(stream(...))` equals
   a list of strings).

3. **`embed_query()` is separate from `embed()`.** Some providers (E5, BGE)
   use a distinct query prefix or model. OpenAI treats them identically,
   but keeping the distinction in the Protocol preserves portability
   without adding per-call branching in service code.

4. **`complete()` and `stream()` take a single rendered prompt string.**
   Prompt templating lives in `retrieval/generate.py`. This means we can
   version prompts independently of providers — a prompt change is not a
   provider change.

5. **`ProviderError` carries `retryable: bool`.** The chat service's
   retry logic (1 retry, then graceful degrade per architecture.md §6)
   only retries when `retryable=True`. Providers set this based on the
   underlying error type (e.g. 429 → retryable, 401 → not).

6. **`model_name` and `dimension` are properties, not attributes.**
   Read-only surface — prevents accidental mutation from a caller, and
   lets implementations compute them from SDK state if needed.

**Dependencies:** stdlib only (`typing.Protocol`, `typing.AsyncIterable`).
No runtime deps. This is intentional — every service imports this module,
so it must have zero import cost beyond stdlib.



### shared/shared/providers/openai_provider.py

**Purpose:** Concrete OpenAI implementations of `EmbeddingProvider` and
`LLMProvider`. Only module in the codebase that imports the `openai` SDK.
Swapping to Anthropic/Ollama means adding a sibling file here, not
touching service code.

**Key design points:**

1. **Client injection, not instantiation.** `AsyncOpenAI` is passed into
   `__init__`. Tests inject a fake; services can share one client instance
   across both providers to reuse the HTTP connection pool.

2. **All SDK exceptions translated to `ProviderError` at the boundary.**
   `_translate_openai_error()` maps each SDK error class to
   `retryable=True|False`. Callers only ever see `ProviderError` — no
   `openai.*` imports leak into service code.

3. **Batched embeddings via `_embed_batch()`.** `embed()` loops in
   `EMBED_BATCH_SIZE=500` chunks and concatenates. Interview answer for
   "what if the corpus grows 100×?" is: tune one constant; the loop and
   ordering guarantee already hold.

4. **Defensive response ordering.** OpenAI returns embeddings with an
   `index` field; we sort by it so output is guaranteed 1:1 with input
   even if the API ever reorders (it shouldn't, but contracts drift).

5. **Streaming via async generator.** `stream()` returns an
   `AsyncIterable[str]`, implemented by `_stream_impl()`. Splitting the
   public method from the impl lets the public signature stay clean
   (no `yield` in the docstring-heavy wrapper) and gives a single place
   to wrap the SDK's stream lifecycle.

6. **Stream lifecycle guarded by `asyncio.shield(response.close())`.**
   If the SSE consumer disconnects mid-stream, the generator's `finally`
   still closes the underlying HTTP response — otherwise we leak
   connections under load.

7. **Empty `choices` / `delta` guarded.** OpenAI occasionally emits
   keep-alive or role-only chunks. We skip them rather than crash.

**Dependencies:** `openai`, `shared.providers.base`. No other internal
imports — this file is intentionally leaf-level.


### shared/shared/schemas/ — Overview

Five files, one clean DAG:

    chunk.py           (domain primitive; stdlib + pydantic only)
        ↑
    ├── ingest.py      (writes Chunks)
    ├── retrieve.py    (reads Chunks, emits ScoredChunks)
    └── citations.py   (views Chunk.metadata as Citation)
            ↑
        chat.py        (references Citation; imports MetadataFilter from retrieve.py)

No cycles. `chunk.py` is import-free relative to the rest of `shared`.

**Key design points:**

1. **`ChunkMetadata` is a nested model, not flat fields on `Chunk`.**
   Chroma's `where` filter operates on metadata keys directly; nesting
   keeps that surface 1:1 with the vector store. Also lets log lines and
   API responses carry metadata without dragging the raw text.

2. **`ChunkMetadata` is `frozen=True`.** Metadata is written once at
   ingest; making it immutable prevents an entire class of "who mutated
   the page number?" bugs. Text stays mutable on `Chunk` because
   post-processing (whitespace normalization, snippet generation) is
   legitimate.

3. **`ScoredChunk` carries a `retriever` tag.** Every stage — dense,
   sparse, rrf, rerank — returns the same shape, tagged with who produced
   it. Ablation scripts and the eval trace use the tag; the API response
   only exposes `retriever="rerank"` rows.

4. **`Citation.from_chunk()` is a classmethod, not a free function.**
   Proximity to the model it constructs, and it makes the transformation
   (Chunk + score → Citation) discoverable via autocomplete.

5. **Citation snippets are leading slices, not windows.** We don't track
   a reranker-visible character range, so a leading slice is honest. The
   `chunk_id` on each citation enables a future "fetch full text" call.

6. **SSE events are one class per type.** The wire format is
   `data: {"type": "token", "text": "..."}\n\n`. `type` is a
   `Literal[...]` so mypy and the frontend's JS consumer agree on the
   enumeration. Discriminated unions are possible but overkill at this
   scale — a single `type` field + separate classes is clearer.

7. **`MetadataFilter` is a typed model, not `dict[str, Any]`.** Callers
   can only express filters the retrieval layer supports. Extending =
   adding a field. This prevents the "user sent a valid Chroma operator
   we don't translate" failure mode at the API boundary.

8. **`ChatRequest.metadata_filter` is a forward reference rebuilt via
   `model_rebuild()`.** This is the only cross-schema import in the set
   (chat → retrieve) and it's one-directional. Documented inline.


### shared/shared/logging/setup.py

**Purpose:** One `configure_logging()` call per service sets up structured
logging; `get_logger(name)` is the only logging entry point services
should use. Keeps `structlog` confined to this file.

**Key design points:**

1. **Auto mode selection (ADR-021).** `local` → pretty colorized; `ci` /
   `prod` → JSON. No manual `LOG_JSON` flag needed in practice; the env
   setting still overrides for edge cases.

2. **`configure_logging()` is idempotent.** Called at import time by each
   `app.py`; calling twice is harmless. Tests can force a reconfigure.

3. **Uvicorn bridge.** Uvicorn's `uvicorn`, `uvicorn.error`,
   `uvicorn.access` loggers are re-parented to the root handler so they
   emit through the same structlog chain. Otherwise dev sees interleaved
   pretty text + raw uvicorn lines.

4. **`color_message` dropped.** Uvicorn attaches this for terminal color;
   it's noise in JSON mode. Dropped unconditionally.

5. **Contextual logging via `structlog.contextvars`.** Not yet wired to a
   FastAPI middleware, but `merge_contextvars` is in the processor chain
   so `structlog.contextvars.bind_contextvars(request_id=...)` from a
   future middleware carries automatically. Zero call-site changes needed.

6. **`get_logger()` wrapper.** Services never `import structlog` — they
   import `get_logger`. One fewer third-party import to trace when
   auditing the codebase, and it gives us a single place to enforce
   conventions (e.g. required context keys) later.

**Dependencies:** `structlog`, `shared.config.settings`. Nothing else.

**ADR-021 (new): Auto log format by environment.**
- **Context:** Dev wants readable logs; prod wants parseable logs.
- **Decision:** Format is a function of `settings.environment`, with
  `LOG_JSON` as an override.
- **Alternatives:** Manual flag everywhere (drift); always JSON (painful
  local dev); always pretty (useless in aggregators).
- **Pros:** Correct by default, one line to override, no config to forget.
- **Cons:** "Why are my logs different in CI?" — documented inline.
- **Status:** Accepted.


### services/ingestion/ingestion/chunker.py

**Purpose:** Split a `LoadedDocument` into `Chunk`s with full
`ChunkMetadata`. Direct implementation of ADR-002 (RecursiveCharacterTextSplitter)
and ADR-008 (metadata schema).

**Key objects:**
- `ChunkerConfig` — `chunk_size`, `chunk_overlap`, validated on construction
- `chunk_document(doc, config) -> list[Chunk]` — the public entry point

**Key private functions:**
- `_looks_like_heading(line)` — heuristic for section detection
- `_extract_section_map(page)` — finds all headings on a page
- `_heading_before_offset(page_text, headings, offset)` — nearest
  preceding heading for a given char offset
- `_build_splitter(chunk_size, chunk_overlap)` — constructs the
  RecursiveCharacterTextSplitter

**Design points:**

1. **Per-page chunking, not document-wide.** Preserves page → chunk
   mapping for citations. Loses a small amount of context at page
   boundaries; acceptable for this corpus.

2. **Separator cascade:** `["\n\n", "\n", ". ", " ", ""]` — paragraph
   first, sentence boundaries next, words, then characters. This is
   ADR-002's choice and the reason chunks don't split mid-sentence
   unless absolutely forced to.

3. **`keep_separator=True`** so paragraph breaks survive into the chunk
   text — helpful for both LLM reading and section detection.

4. **Section detection via a line-based heuristic:**
   - ALL-CAPS lines (with letters) are headings
   - "N. Title" numbered headings are headings
   - Title-case 2–7 word lines with no trailing punctuation are headings
   - Explicit rejects: "Page 12" markers, anything ending in `.` `,` `;`

   This is deliberately conservative — false positives (marking a
   normal line as a heading) are worse than false negatives (missing a
   heading), because a wrong section label appears in citations.

5. **Offset tracking by `find` with a moving cursor.** LangChain's
   `split_text` doesn't return offsets, so we recover them by searching
   the page text forward from the previous chunk's start. This handles
   overlap correctly (search_from = local_start + 1, not local_end).
   Falls back to sequential estimation if `find` fails — defensive
   against LangChain normalizing whitespace in ways we don't see.

6. **`char_start` / `char_end` are document-wide offsets.** We add
   `page.char_start` (from the loader) to the local page offset, so a
   chunk's `[char_start, char_end)` slices `doc.full_text` exactly.
   This is what makes future "scroll to source" UI features trivial.

7. **`chunk_index` is document-global, not per-page.** Monotonic across
   the whole doc. Two reasons: (a) it's a cheap stable sort key, (b) it
   matches the mental model of "chunk 34 of 41".

8. **`ChunkerConfig` validates overlap < size in `__post_init__`.**
   Catches a config error before it produces infinite-loop behavior in
   some splitters. Matches the validator in `settings.py`.

9. **uuid4 per chunk, not a deterministic ID.** We could derive
   `chunk_id` from `hash(doc_hash + chunk_index)` for reproducibility.
   We don't — because it would leak across re-ingest runs and confuse
   "is this the same chunk?" checks. `doc_hash` on the metadata is the
   idempotency key; `chunk_id` is a per-run handle.

**Dependencies:** `langchain-text-splitters`, `shared.schemas`,
`shared.logging`, `ingestion.loader`.

**Not yet wired:** the splitter currently runs one page at a time and
doesn't seed overlap from the previous page. If we later notice chunk
boundaries at page transitions losing context, we can pre-join pages
before splitting and compute page attribution post-hoc. Deferred until
there's evidence it matters.


### services/ingestion/ingestion/ingest.py

**Purpose:** Orchestrates load → chunk → embed → store. Owns the Chroma
client, the BM25 pickle + JSON docstore, idempotency, and the
`check_consistency()` startup check.

**Public API:**
- `ingest_document(pdf_path, force, embedder, chunker_config) -> IngestResult`
- `check_consistency() -> dict` — startup sanity check
- `get_chroma_client()` / `get_or_create_collection(client)` — helpers
- `IngestError` — structural failure

**Design points:**

1. **Embedded `PersistentClient` (ADR-001, decision 1A).** Data lives at
   `settings.chroma_dir`. `anonymized_telemetry=False` removes Chroma's
   PostHog ping — no network dependency at startup.

2. **Sentinel row for O(1) idempotency.** The doc_hash of the currently
   ingested document is stored in a special row with
   `chunk_index = -1` and ID `__ingest_sentinel__`. Checking
   "have I already ingested this?" is one `coll.get([sentinel])`, not a
   metadata scan. Retrieval filters `chunk_index >= 0` to skip it.

3. **`force=True` wipes the collection first.** Otherwise old chunks
   from a previous PDF version would linger. The wipe is logged; if it
   fails we log a warning rather than crash (best-effort, per ADR on
   consistency).

4. **BM25 uses plain whitespace tokenization.** No stemmer, no
   stopwords. Rationale: (a) the handbook is full of acronyms (SSO,
   RBAC, PII, SOC2) that stemmers mangle or stopword-lists strip, (b)
   BM25's IDF term already downweights common words, (c) fewer deps.

5. **docstore.json is human-readable.** `cat data/bm25/docstore.json |
   head` shows real chunks. This is a real debugging win — no need to
   spin up Chroma to inspect what got indexed.

6. **`embedder` is injectable.** Tests pass a fake provider that returns
   deterministic vectors. Production calls `get_embedding_provider()`
   from the factory (Ollama by default).

7. **Consistency is checked, not enforced (decision 3a).** If Chroma
   upsert succeeds but `_save_bm25` raises, we leave the index
   half-written and log. `check_consistency()` at service startup
   catches it: "chroma_count != docstore_count + 1" triggers a WARNING
   with a remediation hint.

8. **`IngestResult` is a frozen dataclass, not a Pydantic model.** It's
   an internal return value, not an API response. `app.py` maps it into
   `shared.schemas.ingest.IngestResponse` at the boundary. Keeps
   `ingest.py` free of schema dependencies beyond `Chunk`.

9. **`_tokenize` is trivial — deliberately.** We want the interviewer
   to ask "why not use NLTK/spaCy?" and the answer to be a crisp
   three-reason justification, not a black box.

**Dependencies:** `chromadb`, `rank-bm25`, `shared.*`,
`ingestion.loader`, `ingestion.chunker`.

**Not handled (documented gaps):**
- Partial failure recovery (best-effort per decision 3a)
- Concurrency — one ingestion at a time, enforced by FastAPI endpoint
  being synchronous-ish at the app layer

  ### services/ingestion/ingestion/app.py

**Purpose:** FastAPI wrapper around the ingestion pipeline. Three
endpoints: `/ingest`, `/health`, `/collections`. Thin — all business
logic lives in `ingest.py`.

**Endpoints:**
- `POST /ingest` — body `IngestRequest`, returns `IngestResponse`
- `GET /health` — service + config echo, no external calls
- `GET /collections` — Chroma collection listing with real chunk counts

**Design points:**

1. **Lifespan runs `check_consistency()` at startup.** Logs OK or
   WARNING with a remediation hint. Does NOT hard-fail — a demo service
   that refuses to boot over index drift is worse than one that logs
   loudly and keeps serving.

2. **Explicit HTTP error mapping:**
   - `LoaderError` → 400 (client error — bad path, unreadable PDF)
   - `ProviderError` → 502 (upstream dependency failure — Ollama down)
   - `IngestError` → 500 (structural — chunker produced 0 chunks)
   - Anything else → 500 with `log.exception()` for full traceback

   This matters for the chat service later: it can distinguish
   retryable (502) from non-retryable (400/500) without parsing strings.

3. **`IngestRequest` allows a `pdf_path` override.** Defaults to
   `settings.source_pdf` when omitted. Enables ingesting a different
   doc without restarting the service.

4. **`/collections` subtracts the sentinel.** Chroma's raw count
   includes our `__ingest_sentinel__` row, so `count = raw - 1` for the
   API response. The sentinel's `doc_hash` is surfaced as
   `CollectionInfo.doc_hash`.

5. **`/health` never touches Chroma or BM25.** It's a liveness probe —
   it must succeed even if the vector store is corrupted. Readiness
   would be a separate `/ready` endpoint if we needed one (we don't,
   for demo scope).

6. **CORS from `settings.frontend_origin` (ADR-014).** Ingestion is
   admin-triggered and usually called from CLI, but allowing the
   frontend origin costs nothing and future-proofs an admin panel.

7. **No auth (documented non-goal).** Architecture §9 lists auth as
   out of scope. In prod we'd add an API key middleware here.

8. **`IngestResult` → `IngestResponse` mapping is explicit.** The
   dataclass is internal; the Pydantic model is the API contract.
   Keeping them separate means the internal shape can change without
   breaking clients (and vice versa).

**Dependencies:** `fastapi`, `shared.*`, `ingestion.ingest`,
`ingestion.loader`.


**Chroma 0.5.x → 0.6.x API note:** `list_collections()` returns
`CollectionName` objects (string-like) in 0.6.x, and `Collection` objects
in 0.5.x. Our handler converts each to `str(item)` and re-fetches via
`client.get_collection(name)`. This works on both versions. If we pin
Chroma tighter in the future (`chromadb==0.6.*`), we can simplify, but
the version-agnostic form costs nothing and prevents silent breakage on
dependency bumps.

### services/retrieval/ — Batch 1 (bm25_index, dense, sparse, fusion)

**Purpose:** Retrieval internals. Load the BM25 + docstore at startup,
expose dense and sparse retrievers with a common `search()` signature,
and combine results with RRF. Reranker, HyDE, and generation come in
Batch 2.

**`bm25_index.py`:**
- `load_index()` reads `bm25.pkl` + `docstore.json` (written by
  ingestion), returns a `BM25Index` with `.search()` and `.get_chunk()`.
- `ordered_chunk_ids` is reconstructed from `docstore[*].metadata.chunk_index`
  sort — because BM25Okapi doesn't persist corpus order, we need the
  docstore's `chunk_index` field to align scores with chunk_ids.
- Tokenizer is duplicated verbatim from `ingestion.ingest._tokenize`.
  If they drift, BM25 scores silently change. Documented in both files.
- `IndexNotReadyError` fires when the pickle or docstore is missing —
  clear failure at startup instead of empty search results at query time.

**`dense.py`:**
- `DenseRetriever` wraps a Chroma collection + an `EmbeddingProvider`
  (injected — no factory call at construction time).
- Sentinel excluded via `{"chunk_index": {"$gte": 0}}` merged with any
  caller-supplied filter. Chroma's `where` semantics use `$and` for
  multiple conditions.
- Distance → score normalization: cosine `1 - d/2`, l2 `1/(1+d)`, ip
  as-is. Keeps scores comparable enough for display and RRF (RRF only
  uses ranks anyway, but the `/retrieve/sync` response shows scores).
- Defensive: invalid metadata rows are logged and skipped, not fatal.

**`sparse.py`:**
- Thin wrapper so `fusion.py` and `app.py` don't care whether sparse
  retrieval is BM25 or something else later. Three methods, no logic.
- Returns `ScoredChunk` with `retriever="sparse"` (set by `BM25Index.search`).

**`fusion.py`:**
- RRF implementation. `k` (default 60) from settings.
- Documents keyed by `chunk_id` — same chunk from dense and sparse
  contributes twice to the RRF score, which is the intended behaviour.
- Representative chunk kept for downstream text/metadata; the *score* is
  always the RRF score.
- Output tagged `retriever="rrf"`.
- Logs input list lengths and unique doc count — useful for ablation
  (`dense only` vs `dense + sparse + rrf`).

**Deferred to Batch 2:** rerank, HyDE, generation, FastAPI app (with
the POST /reload stub), Dockerfile.

**Dependencies:** `rank-bm25`, `chromadb`, `shared.*`.

**Startup contract:** `app.py` (Batch 2) will call `load_index()` in
lifespan and stash the `BM25Index` + `DenseRetriever` on `app.state`.