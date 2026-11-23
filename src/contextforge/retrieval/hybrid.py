"""Online retrieval: BM25 + vector search, rank fusion, optional rerank, access validation."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from contextforge.access_control.models import User, access_filter_for, can_access
from contextforge.common.metrics import Metrics
from contextforge.common.models import Hit
from contextforge.embeddings import Embedder
from contextforge.indexing.base import KeywordIndex, VectorIndex
from contextforge.reranking import Reranker
from contextforge.retrieval.fusion import reciprocal_rank_fusion
from contextforge.storage import Repository, session_scope

logger = logging.getLogger(__name__)

MODES = ("bm25", "vector", "hybrid")


class RetrievalError(Exception):
    pass


@dataclass
class SearchResponse:
    query: str
    mode: str
    rerank: bool
    hits: list[Hit]
    timings_ms: dict[str, float] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)


class HybridRetriever:
    def __init__(
        self,
        session_factory,
        embedder: Embedder,
        vector_index: VectorIndex,
        keyword_index: KeywordIndex,
        reranker: Reranker | None = None,
        rrf_k: int = 60,
        weights: dict[str, float] | None = None,
        candidate_pool: int = 30,
        rerank_candidates: int = 20,
        metrics: Metrics | None = None,
    ):
        self.sf = session_factory
        self.embedder = embedder
        self.vectors = vector_index
        self.keywords = keyword_index
        self.reranker = reranker
        self.rrf_k = rrf_k
        self.weights = weights or {"bm25": 1.0, "vector": 1.0}
        self.candidate_pool = candidate_pool
        self.rerank_candidates = rerank_candidates
        self.metrics = metrics or Metrics()

    def search(
        self,
        query: str,
        user: User,
        mode: str = "hybrid",
        top_k: int = 5,
        rerank: bool = False,
        document_version: int | None = None,
    ) -> SearchResponse:
        if mode not in MODES:
            raise RetrievalError(f"unknown mode {mode!r}; expected one of {MODES}")
        if not query.strip():
            raise RetrievalError("query must not be empty")
        if rerank and self.reranker is None:
            raise RetrievalError("reranking was requested but no reranker is configured")

        t0 = time.perf_counter()
        timings: dict[str, float] = {}
        counts: dict[str, int] = {}
        access = access_filter_for(user)
        pool = max(self.candidate_pool, top_k)

        def run_bm25() -> tuple[list[Hit], float]:
            t = time.perf_counter()
            return self.keywords.search(query, pool, access, document_version), time.perf_counter() - t

        def run_vector() -> tuple[list[Hit], float, float]:
            t = time.perf_counter()
            vec = self.embedder.embed_query(query)
            t_embed = time.perf_counter() - t
            hits = self.vectors.search(vec, pool, access, document_version)
            return hits, time.perf_counter() - t - t_embed, t_embed

        rankings: dict[str, list[Hit]] = {}
        if mode == "hybrid":
            with ThreadPoolExecutor(max_workers=2) as pool_exec:
                f_bm25, f_vec = pool_exec.submit(run_bm25), pool_exec.submit(run_vector)
                rankings["bm25"], timings["bm25_ms"] = _ms(f_bm25.result())
                rankings["vector"], timings["vector_ms"], timings["embed_ms"] = _ms3(f_vec.result())
        elif mode == "bm25":
            rankings["bm25"], timings["bm25_ms"] = _ms(run_bm25())
        else:
            rankings["vector"], timings["vector_ms"], timings["embed_ms"] = _ms3(run_vector())
        counts.update({f"{name}_candidates": len(h) for name, h in rankings.items()})

        t = time.perf_counter()
        if mode == "hybrid":
            candidates = reciprocal_rank_fusion(rankings, k=self.rrf_k, weights=self.weights)
        else:
            candidates = next(iter(rankings.values()))
        timings["fusion_ms"] = (time.perf_counter() - t) * 1000

        if rerank:
            t = time.perf_counter()
            candidates = self.reranker.rerank(query, candidates, top_n=max(self.rerank_candidates, top_k))
            timings["rerank_ms"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        allowed = self._validate(candidates, user)
        timings["validate_ms"] = (time.perf_counter() - t) * 1000
        counts["dropped_by_validation"] = len(candidates) - len(allowed)

        hits = allowed[:top_k]
        counts["returned"] = len(hits)
        timings["total_ms"] = (time.perf_counter() - t0) * 1000
        timings = {k: round(v, 3) for k, v in timings.items()}

        self.metrics.inc("search_requests", mode=mode, rerank=str(rerank).lower())
        self.metrics.observe("search_latency_ms", timings["total_ms"], mode=mode)
        self.metrics.observe("search_result_count", len(hits), mode=mode)
        return SearchResponse(query, mode, rerank, hits, timings, counts)

    def _validate(self, hits: list[Hit], user: User) -> list[Hit]:
        """Second, independent access check against the system of record.

        Index payloads can be stale (ACL changed, document deleted, newer version pending).
        PostgreSQL is authoritative, so a hit survives only if its document still exists, is
        visible to the user *now*, and the hit belongs to the document's indexed version.
        """
        if not hits:
            return []
        with session_scope(self.sf) as session:
            docs = Repository(session).get_documents(list({h.document_id for h in hits}))
        kept = []
        for hit in hits:
            doc = docs.get(hit.document_id)
            if (
                doc is not None
                and doc.status != "deleted"
                and doc.indexed_version == hit.document_version
                and can_access(user, doc.tenant_id, doc.owner_id, doc.allowed_groups)
            ):
                kept.append(hit)
        return kept


def _ms(result):
    hits, seconds = result
    return hits, seconds * 1000


def _ms3(result):
    hits, seconds, embed_seconds = result
    return hits, seconds * 1000, embed_seconds * 1000
