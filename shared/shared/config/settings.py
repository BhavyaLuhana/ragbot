"""
Central configuration for the entire RAG system.

All services (ingestion, retrieval, chat) import a single `settings`
singleton from here. Values are loaded from environment variables (and
`.env` in local dev) via pydantic-settings, validated on import, and
fail fast at startup if anything required is missing.

Design notes:
- One Settings class, one source of truth. No scattered os.getenv calls.
- Every field has a default where a sensible one exists — so local dev
  works with only OPENAI_API_KEY set.
- Provider names are strings, not imports, so swapping providers is a
  config change, not a code change (ADR-016).
- Paths are resolved relative to the repo root, not CWD, so services
  behave identically under uvicorn, pytest, and docker-compose.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ─────────────────────────────────────────────────────────────
# Path resolution
# ─────────────────────────────────────────────────────────────
# settings.py lives at: <repo>/shared/shared/config/settings.py
# parents[0] = config/
# parents[1] = shared/
# parents[2] = shared/           (the inner package)
# parents[3] = repo root
REPO_ROOT: Path = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Single source of truth for runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Environment ──────────────────────────────────────────
    environment: Literal["local", "ci", "prod"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = False  # pretty logs in local dev, JSON in prod

    # ── Paths ────────────────────────────────────────────────
    repo_root: Path = REPO_ROOT
    data_dir: Path = REPO_ROOT / "data"
    raw_dir: Path = REPO_ROOT / "data" / "raw"
    chroma_dir: Path = REPO_ROOT / "data" / "chroma"
    bm25_dir: Path = REPO_ROOT / "data" / "bm25"
    eval_dir: Path = REPO_ROOT / "data" / "eval"

    source_pdf: Path = REPO_ROOT / "data" / "raw" / "TechCorp_Internal_Engineering_Handbook.pdf"

    # ── Chroma ───────────────────────────────────────────────
    chroma_collection: str = "techcorp_handbook"
    chroma_distance: Literal["cosine", "l2", "ip"] = "cosine"

    # ── BM25 ─────────────────────────────────────────────────
    bm25_pickle: Path = REPO_ROOT / "data" / "bm25" / "bm25.pkl"
    bm25_docstore: Path = REPO_ROOT / "data" / "bm25" / "docstore.json"

    # ── Chunking (ADR-002) ───────────────────────────────────
    chunk_size: int = 800
    chunk_overlap: int = 150

    # ── Retrieval ────────────────────────────────────────────
    dense_top_k: int = 20
    sparse_top_k: int = 20
    fusion_top_k: int = 20
    final_top_k: int = 5
    rrf_k: int = 60  # ADR-005

    # ── Feature toggles (ablation switches, ADR-009) ────────
    hyde_enabled: bool = True          # ADR-007
    retrieval_dense_only: bool = False # ablation: skip BM25 + RRF
    retrieval_hybrid: bool = True      # ablation: use dense + sparse + RRF
    retrieval_rerank: bool = True      # ablation: run cross-encoder

    # ── Providers (ADR-016) ──────────────────────────────────
    embedding_provider: Literal["openai"] = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536

    llm_provider: Literal["openai"] = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 800

    openai_api_key: SecretStr | None = None

    # ── Reranker (ADR-006) ───────────────────────────────────
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    reranker_device: Literal["cpu", "cuda", "mps"] = "cpu"

    # ── Service URLs (chat → retrieval, ingestion admin) ────
    ingestion_url: str = "http://localhost:8001"
    retrieval_url: str = "http://localhost:8002"
    chat_url: str = "http://localhost:8003"
    frontend_origin: str = "http://localhost:5173"

    # ── HTTP / SSE ───────────────────────────────────────────
    http_timeout_seconds: float = 30.0
    http_max_retries: int = 1
    sse_heartbeat_seconds: int = 15

    # ── RAGAS / eval (ADR-009) ───────────────────────────────
    eval_set_path: Path = REPO_ROOT / "data" / "eval" / "qa_set.json"
    manual_queries_path: Path = REPO_ROOT / "data" / "eval" / "manual_queries.json"
    eval_results_path: Path = REPO_ROOT / "data" / "eval" / "results.json"
    ablation_results_path: Path = REPO_ROOT / "data" / "eval" / "ablation.csv"
    eval_set_size: int = 25

    # ── Session / chat ───────────────────────────────────────
    session_max_turns: int = 10
    session_ttl_seconds: int = 3600

    # ── Validators ───────────────────────────────────────────
    @field_validator("openai_api_key", mode="before")
    @classmethod
    def _empty_string_to_none(cls, v: object) -> object:
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @field_validator("chunk_overlap")
    @classmethod
    def _overlap_lt_size(cls, v: int, info) -> int:
        size = info.data.get("chunk_size", 800)
        if v >= size:
            raise ValueError(f"chunk_overlap ({v}) must be < chunk_size ({size})")
        return v

    # ── Derived helpers ──────────────────────────────────────
    def require_openai_key(self) -> str:
        """Fail fast when a code path actually needs the key."""
        if self.openai_api_key is None:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Add it to .env or export it."
            )
        return self.openai_api_key.get_secret_value()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton accessor."""
    return Settings()


settings: Settings = get_settings()