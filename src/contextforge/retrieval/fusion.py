"""Reciprocal Rank Fusion.

score(d) = sum over rankings r of  weight_r / (k + rank_r(d))      (rank starts at 1)

Only ranks are used, so BM25 scores (unbounded) and cosine similarities (about 0..1) never need
to be normalized against each other. A larger `k` flattens the advantage of top ranks; 60 is the
value from the original RRF paper. Weights let one retriever count for more.
"""

from contextforge.common.models import Hit


def reciprocal_rank_fusion(
    rankings: dict[str, list[Hit]],
    k: int = 60,
    weights: dict[str, float] | None = None,
    top_n: int | None = None,
) -> list[Hit]:
    if k <= 0:
        raise ValueError("RRF k must be positive")
    weights = weights or {}
    fused: dict[str, Hit] = {}
    totals: dict[str, float] = {}
    best_rank: dict[str, int] = {}

    for name, hits in rankings.items():
        weight = weights.get(name, 1.0)
        for rank, hit in enumerate(hits, start=1):
            if hit.chunk_id not in fused:
                fused[hit.chunk_id] = Hit(**{**hit.__dict__, "signals": {}})
                totals[hit.chunk_id] = 0.0
                best_rank[hit.chunk_id] = rank
            totals[hit.chunk_id] += weight / (k + rank)
            best_rank[hit.chunk_id] = min(best_rank[hit.chunk_id], rank)
            fused[hit.chunk_id].signals[f"{name}_rank"] = rank
            fused[hit.chunk_id].signals[f"{name}_score"] = hit.score

    ordered = sorted(fused, key=lambda cid: (-totals[cid], best_rank[cid], cid))
    result = []
    for cid in ordered:
        hit = fused[cid]
        hit.score = totals[cid]
        hit.signals["rrf_score"] = totals[cid]
        result.append(hit)
    return result[:top_n] if top_n else result
