from contextforge.evaluation.metrics import (
    hit_rate_at_k,
    percentile,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from contextforge.reranking import Reranker
from contextforge.retrieval.query import parse_query

from .helpers import make_hit


def test_reranker_reorders_by_scorer_and_records_signals():
    hits = [make_hit("a", 0.9), make_hit("b", 0.5), make_hit("c", 0.1)]
    scores = {"a": 0.1, "b": 0.9, "c": 0.5}
    reranker = Reranker(lambda q, texts: [scores[t] for t in texts])
    out = reranker.rerank("q", hits)
    assert [h.chunk_id for h in out] == ["b", "c", "a"]
    assert out[0].signals["rerank_score"] == 0.9 and out[0].signals["pre_rerank_score"] == 0.5


def test_reranker_top_n_keeps_the_tail_in_place():
    hits = [make_hit(i, 1) for i in "abcd"]
    reranker = Reranker(lambda q, texts: [1.0 if t == "b" else 0.0 for t in texts])
    assert [h.chunk_id for h in reranker.rerank("q", hits, top_n=2)] == ["b", "a", "c", "d"]


def test_reranker_handles_empty_input():
    assert Reranker(lambda q, t: []).rerank("q", []) == []


def test_recall_precision_hit_rate_mrr():
    retrieved = ["c1", "c2", "c3", "c4"]
    relevant = {"c2", "c4", "c9"}
    assert precision_at_k(retrieved, relevant, 4) == 0.5
    assert precision_at_k(retrieved, relevant, 1) == 0.0
    assert hit_rate_at_k(retrieved, relevant, 1) == 0.0
    assert hit_rate_at_k(retrieved, relevant, 2) == 1.0
    assert reciprocal_rank(retrieved, relevant) == 0.5
    assert reciprocal_rank(["x"], relevant) == 0.0


def test_document_recall_counts_distinct_expected_documents():
    paths = ["a.md", "a.md", "b.md"]
    assert recall_at_k(paths, ["a.md", "b.md"], 2) == 0.5
    assert recall_at_k(paths, ["a.md", "b.md"], 3) == 1.0
    assert recall_at_k(paths, [], 3) == 0.0


def test_percentile_nearest_rank():
    assert percentile([10, 20, 30, 40], 50) == 20
    assert percentile([10, 20, 30, 40], 95) == 40
    assert percentile([], 50) == 0.0


def test_parse_query_separates_phrases():
    q = parse_query('rollback "gwctl rollback" now')
    assert q.phrases == ("gwctl rollback",) and q.free_text == "rollback now"
    assert parse_query("plain").phrases == ()

