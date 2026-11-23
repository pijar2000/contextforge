import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from contextforge.access_control.models import User
from contextforge.evaluation.metrics import (
    hit_rate_at_k,
    percentile,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from contextforge.retrieval import HybridRetriever
from contextforge.storage import Repository, session_scope

logger = logging.getLogger(__name__)

STRATEGIES: dict[str, dict] = {
    "bm25": {"mode": "bm25", "rerank": False},
    "vector": {"mode": "vector", "rerank": False},
    "hybrid": {"mode": "hybrid", "rerank": False},
    "hybrid_rerank": {"mode": "hybrid", "rerank": True},
}
DEFAULT_KS = (1, 3, 5, 10)


@dataclass
class EvalQuery:
    id: str
    question: str
    category: str
    expected_sources: list[str]
    expected_keywords: list[str]


def load_dataset(path: Path) -> list[EvalQuery]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [EvalQuery(**q) for q in raw["queries"]]


def relevant_chunks_for(session_factory, tenant_id: str, queries: list[EvalQuery]) -> dict[str, set[str]]:
    """Derive relevance judgments from the *currently indexed* chunks."""
    from sqlalchemy import select

    from contextforge.storage.models import Document

    with session_scope(session_factory) as session:
        docs = {
            d.source_path: d.document_id
            for d in session.scalars(
                select(Document).where(Document.tenant_id == tenant_id, Document.status == "indexed")
            )
        }
        repo = Repository(session)
        needed = {s for q in queries for s in q.expected_sources}
        chunks = repo.chunks_for_documents([docs[s] for s in needed if s in docs])
        by_path: dict[str, list] = {}
        reverse = {v: k for k, v in docs.items()}
        for c in chunks:
            by_path.setdefault(reverse[c.document_id], []).append((c.chunk_id, c.text.lower()))

    result: dict[str, set[str]] = {}
    for q in queries:
        keywords = [k.lower() for k in q.expected_keywords]
        result[q.id] = {
            cid
            for src in q.expected_sources
            for cid, text in by_path.get(src, [])
            if any(k in text for k in keywords)
        }
    return result


@dataclass
class EvaluationResult:
    config: dict
    per_query: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"config": self.config, "summary": self.summary, "per_query": self.per_query}


def evaluate(
    retriever: HybridRetriever,
    session_factory,
    user: User,
    queries: list[EvalQuery],
    strategies: list[str] | None = None,
    ks: tuple[int, ...] = DEFAULT_KS,
    repeats: int = 1,
    config: dict | None = None,
) -> EvaluationResult:
    strategies = strategies or list(STRATEGIES)
    relevant = relevant_chunks_for(session_factory, user.tenant_id, queries)
    max_k = max(ks)
    result = EvaluationResult(config=config or {})
    result.config.update({"ks": list(ks), "queries": len(queries), "repeats": repeats, "user": user.user_id})

    unjudged = [q.id for q in queries if not relevant[q.id]]
    if unjudged:
        logger.warning("queries without any relevant chunk (excluded from metrics): %s", unjudged)
    judged = [q for q in queries if relevant[q.id]]
    result.config["queries_judged"] = len(judged)
    result.config["queries_without_relevant_chunks"] = unjudged

    for name in strategies:
        opts = STRATEGIES[name]
        rows = []
        latencies: list[float] = []
        for q in judged:
            best_ms = None
            for _ in range(repeats):
                resp = retriever.search(q.question, user, top_k=max_k, **opts)
                total = resp.timings_ms["total_ms"]
                best_ms = total if best_ms is None else min(best_ms, total)
            latencies.append(best_ms)
            chunk_ids = [h.chunk_id for h in resp.hits]
            doc_paths = [h.source_path for h in resp.hits]
            rel = relevant[q.id]
            row = {
                "strategy": name,
                "query_id": q.id,
                "category": q.category,
                "latency_ms": best_ms,
                "mrr": reciprocal_rank(chunk_ids, rel),
                "retrieved": [{"chunk_id": h.chunk_id, "source_path": h.source_path} for h in resp.hits],
            }
            for k in ks:
                row[f"recall@{k}"] = recall_at_k(doc_paths, q.expected_sources, k)
                row[f"precision@{k}"] = precision_at_k(chunk_ids, rel, k)
                row[f"hit_rate@{k}"] = hit_rate_at_k(chunk_ids, rel, k)
            rows.append(row)
        result.per_query.extend(rows)

        n = len(rows) or 1
        summary = {"queries": len(rows), "mrr": sum(r["mrr"] for r in rows) / n}
        for k in ks:
            for metric in ("recall", "precision", "hit_rate"):
                summary[f"{metric}@{k}"] = sum(r[f"{metric}@{k}"] for r in rows) / n
        summary["latency_ms_mean"] = sum(latencies) / n
        summary["latency_ms_p50"] = percentile(latencies, 50)
        summary["latency_ms_p95"] = percentile(latencies, 95)
        result.summary[name] = summary
    return result
