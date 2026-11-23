"""Deterministic retrieval metrics.

Definitions used throughout this project (also in docs/evaluation.md):
  relevant chunk   a chunk from an expected source document that contains at least one of the
                   query's expected keywords (case-insensitive)
  Recall@K         fraction of the expected source documents that appear in the top K results
  Precision@K      relevant chunks in the top K, divided by K
  Hit Rate@K       1 if any relevant chunk is in the top K, else 0
  MRR              1 / rank of the first relevant chunk (0 if none is retrieved)
"""

import math


def recall_at_k(retrieved_doc_paths: list[str], expected_docs: list[str], k: int) -> float:
    if not expected_docs:
        return 0.0
    found = set(retrieved_doc_paths[:k]) & set(expected_docs)
    return len(found) / len(set(expected_docs))


def precision_at_k(retrieved_chunk_ids: list[str], relevant: set[str], k: int) -> float:
    if k <= 0:
        return 0.0
    return sum(1 for c in retrieved_chunk_ids[:k] if c in relevant) / k


def hit_rate_at_k(retrieved_chunk_ids: list[str], relevant: set[str], k: int) -> float:
    return 1.0 if any(c in relevant for c in retrieved_chunk_ids[:k]) else 0.0


def reciprocal_rank(retrieved_chunk_ids: list[str], relevant: set[str]) -> float:
    for rank, cid in enumerate(retrieved_chunk_ids, start=1):
        if cid in relevant:
            return 1.0 / rank
    return 0.0


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil(pct / 100 * len(ordered)) - 1))
    return ordered[idx]
