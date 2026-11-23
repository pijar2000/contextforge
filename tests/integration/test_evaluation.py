import json

import pytest

pytest.importorskip("fitz")

from contextforge.evaluation import STRATEGIES, evaluate, load_dataset, render_markdown, write_report  # noqa: E402


def test_dataset_is_consistent_with_the_sample_corpus(services, run_ingest, users):
    """Every query must have at least one relevant chunk, otherwise the dataset drifted."""
    run_ingest()
    queries = load_dataset(services.settings.evaluation_dataset)
    result = evaluate(services.retriever, services.session_factory, users["alice"], queries, ks=(1, 5))
    assert result.config["queries_without_relevant_chunks"] == []
    assert result.config["queries_judged"] == len(queries)


def test_evaluation_compares_all_strategies_with_valid_metrics(services, run_ingest, users, tmp_path):
    run_ingest()
    queries = load_dataset(services.settings.evaluation_dataset)
    result = evaluate(services.retriever, services.session_factory, users["alice"], queries)
    assert set(result.summary) == set(STRATEGIES)
    for summary in result.summary.values():
        for key, value in summary.items():
            if key.startswith(("recall", "precision", "hit_rate", "mrr")):
                assert 0.0 <= value <= 1.0, key
        assert summary["latency_ms_p95"] >= summary["latency_ms_p50"] >= 0
    # Exact identifiers are the case BM25 exists for.
    exact = [r for r in result.per_query if r["strategy"] == "bm25" and r["category"] == "exact_keyword"]
    assert exact and all(r["hit_rate@10"] == 1.0 for r in exact)

    json_path, md_path = write_report(result, tmp_path)
    assert json.loads(json_path.read_text())["summary"]["hybrid"]["queries"] == len(queries)
    report = md_path.read_text()
    assert "hybrid_rerank minus hybrid" in report and "By query category" in report


def test_metrics_are_deterministic_across_runs(services, run_ingest, users):
    run_ingest()
    queries = load_dataset(services.settings.evaluation_dataset)[:8]
    a = evaluate(services.retriever, services.session_factory, users["alice"], queries, strategies=["bm25", "hybrid"])
    b = evaluate(services.retriever, services.session_factory, users["alice"], queries, strategies=["bm25", "hybrid"])
    for name in ("bm25", "hybrid"):
        assert a.summary[name]["mrr"] == b.summary[name]["mrr"]
        assert a.summary[name]["recall@5"] == b.summary[name]["recall@5"]


def test_report_renders_without_rerank_strategy(services, run_ingest, users):
    run_ingest()
    queries = load_dataset(services.settings.evaluation_dataset)[:3]
    result = evaluate(services.retriever, services.session_factory, users["alice"], queries, strategies=["bm25"])
    assert "Effect of reranking" not in render_markdown(result)
