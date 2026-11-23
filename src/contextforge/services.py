"""Wires configuration into concrete components (the only place that knows every backend)."""

import tempfile
from dataclasses import dataclass
from pathlib import Path

from contextforge.access_control.directory import UserDirectory
from contextforge.access_control.policy import PolicyResolver
from contextforge.assistant import Assistant, OpenAICompatibleClient
from contextforge.chunking import ChunkingConfig
from contextforge.common.config import Settings
from contextforge.common.metrics import Metrics
from contextforge.embeddings import Embedder, build_embedder
from contextforge.indexing.base import KeywordIndex, VectorIndex
from contextforge.indexing.memory import InMemoryKeywordIndex, InMemoryVectorIndex
from contextforge.ingestion.pipeline import IngestionPipeline
from contextforge.reranking import CrossEncoderScorer, Reranker
from contextforge.retrieval import HybridRetriever
from contextforge.storage import (
    LocalObjectStore,
    MinioObjectStore,
    ObjectStore,
    init_db,
    make_engine,
    make_session_factory,
)


@dataclass
class Services:
    settings: Settings
    session_factory: object
    object_store: ObjectStore
    embedder: Embedder
    vector_index: VectorIndex
    keyword_index: KeywordIndex
    reranker: Reranker | None
    retriever: HybridRetriever
    pipeline: IngestionPipeline
    assistant: Assistant
    users: UserDirectory
    policy: PolicyResolver
    metrics: Metrics

    def ping(self) -> dict[str, bool]:
        from sqlalchemy import text

        try:
            with self.session_factory() as s:
                s.execute(text("SELECT 1"))
            db_ok = True
        except Exception:
            db_ok = False
        return {
            "postgres": db_ok,
            "object_store": self.object_store.ping(),
            "qdrant": self.vector_index.ping(),
            "opensearch": self.keyword_index.ping(),
        }


def build_services(
    settings: Settings,
    *,
    embedder: Embedder | None = None,
    vector_index: VectorIndex | None = None,
    keyword_index: KeywordIndex | None = None,
    object_store: ObjectStore | None = None,
    database_url: str | None = None,
    reranker: Reranker | None = None,
) -> Services:
    """Build the component graph. Keyword overrides exist so tests can inject fakes."""
    local = settings.backend == "local"
    url = database_url or ("sqlite://" if local else settings.database_url)
    engine = make_engine(url)
    init_db(engine)
    session_factory = make_session_factory(engine)

    if object_store is None:
        object_store = (
            LocalObjectStore(Path(tempfile.mkdtemp(prefix="contextforge-")))
            if local
            else MinioObjectStore(
                settings.minio_endpoint,
                settings.minio_access_key,
                settings.minio_secret_key,
                settings.minio_bucket,
                settings.minio_secure,
            )
        )
    if vector_index is None:
        if local:
            vector_index = InMemoryVectorIndex()
        else:
            from contextforge.indexing.qdrant_index import QdrantVectorIndex

            vector_index = QdrantVectorIndex(
                settings.qdrant_url, settings.qdrant_collection, settings.embedding_dim
            )
    if keyword_index is None:
        if local:
            keyword_index = InMemoryKeywordIndex()
        else:
            from contextforge.indexing.opensearch_index import OpenSearchKeywordIndex

            keyword_index = OpenSearchKeywordIndex(settings.opensearch_url, settings.opensearch_index)

    embedder = embedder or build_embedder(settings)
    reranker = reranker or Reranker(CrossEncoderScorer(settings.reranker_model), settings.reranker_model)
    metrics = Metrics()
    policy = PolicyResolver.from_file(settings.access_policy_file)
    users = UserDirectory.from_file(settings.users_file)

    pipeline = IngestionPipeline(
        session_factory,
        object_store,
        embedder,
        vector_index,
        keyword_index,
        policy,
        ChunkingConfig(
            settings.chunk_strategy, settings.chunk_size, settings.chunk_overlap, settings.chunk_min_size
        ),
        metrics,
    )
    retriever = HybridRetriever(
        session_factory,
        embedder,
        vector_index,
        keyword_index,
        reranker,
        rrf_k=settings.rrf_k,
        weights={"bm25": settings.rrf_weight_bm25, "vector": settings.rrf_weight_vector},
        candidate_pool=settings.candidate_pool,
        rerank_candidates=settings.rerank_candidates,
        metrics=metrics,
    )
    llm = (
        OpenAICompatibleClient(
            settings.llm_base_url, settings.llm_model, settings.llm_api_key, settings.llm_timeout_seconds
        )
        if settings.llm_base_url and settings.llm_model
        else None
    )
    return Services(
        settings, session_factory, object_store, embedder, vector_index, keyword_index, reranker,
        retriever, pipeline, Assistant(retriever, llm), users, policy, metrics,
    )


def prepare_backends(services: Services) -> None:
    """Create buckets, collections and indices if they do not exist yet."""
    services.object_store.ensure()
    services.vector_index.ensure()
    services.keyword_index.ensure()
