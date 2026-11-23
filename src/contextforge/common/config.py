"""Runtime configuration. Every value can be overridden through environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # "services" = Postgres + MinIO + Qdrant + OpenSearch.
    # "local" = in-memory SQLite + temp-dir object store + in-memory indexes (nothing persists).
    backend: str = "services"

    database_url: str = (
        "postgresql+psycopg://contextforge:contextforge_dev@localhost:5432/contextforge"
    )

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "contextforge"
    minio_secret_key: str = "contextforge_dev_secret"
    minio_bucket: str = "contextforge-raw"
    minio_secure: bool = False

    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "contextforge_chunks"
    opensearch_url: str = "http://localhost:9200"
    opensearch_index: str = "contextforge-chunks"

    # "sentence-transformers" for real embeddings, "hashing" for a deterministic offline fallback.
    embedding_backend: str = "sentence-transformers"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384
    embedding_query_prefix: str = ""
    embedding_batch_size: int = 32
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    chunk_strategy: str = "structure"  # "structure" or "fixed"
    chunk_size: int = 1000  # characters
    chunk_overlap: int = 150  # characters
    chunk_min_size: int = 200  # structure-aware: sections below this are merged forward

    rrf_k: int = 60
    rrf_weight_bm25: float = 1.0
    rrf_weight_vector: float = 1.0
    candidate_pool: int = 30
    rerank_candidates: int = 20

    tenant_id: str = "halvorsen"
    source_name: str = "local-fs"
    source_root: Path = Path("datasets/sample_documents")
    access_policy_file: Path = Path("config/access_policies.yaml")
    users_file: Path = Path("config/users.yaml")

    llm_base_url: str = ""  # e.g. http://localhost:11434/v1 (Ollama) or any OpenAI-compatible URL
    llm_model: str = ""
    llm_api_key: str = ""
    llm_timeout_seconds: float = 60.0

    evaluation_dataset: Path = Path("datasets/evaluation/queries.json")
    evaluation_report_dir: Path = Path("reports/evaluation")
    staging_dir: Path = Path("data/staging")
    log_level: str = "INFO"
    api_url: str = "http://localhost:8000"  # used by the dashboard


@lru_cache
def get_settings() -> Settings:
    return Settings()
