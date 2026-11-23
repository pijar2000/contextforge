import pytest

from contextforge.retrieval.fusion import reciprocal_rank_fusion

from .helpers import make_hit


def rank(*ids):
    return [make_hit(i, 1.0 / (n + 1)) for n, i in enumerate(ids)]


def test_rrf_scores_match_formula():
    fused = reciprocal_rank_fusion({"bm25": rank("a", "b"), "vector": rank("b", "c")}, k=60)
    scores = {h.chunk_id: h.score for h in fused}
    assert scores["a"] == pytest.approx(1 / 61)
    assert scores["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert scores["c"] == pytest.approx(1 / 62)
    assert [h.chunk_id for h in fused] == ["b", "a", "c"]


def test_document_in_both_lists_beats_single_list_top_rank():
    fused = reciprocal_rank_fusion({"bm25": rank("x", "shared"), "vector": rank("y", "shared")})
    assert fused[0].chunk_id == "shared"


def test_results_are_deduplicated_and_signals_recorded():
    fused = reciprocal_rank_fusion({"bm25": rank("a"), "vector": rank("a")})
    assert len(fused) == 1
    assert fused[0].signals["bm25_rank"] == 1 and fused[0].signals["vector_rank"] == 1


def test_weights_change_the_order():
    rankings = {"bm25": rank("a", "b"), "vector": rank("b", "a")}
    assert reciprocal_rank_fusion(rankings, weights={"bm25": 3.0})[0].chunk_id == "a"
    assert reciprocal_rank_fusion(rankings, weights={"vector": 3.0})[0].chunk_id == "b"


def test_larger_k_flattens_rank_differences():
    r = {"bm25": rank("a", "b")}
    gap_small = abs(reciprocal_rank_fusion(r, k=1)[0].score - reciprocal_rank_fusion(r, k=1)[1].score)
    gap_large = abs(reciprocal_rank_fusion(r, k=1000)[0].score - reciprocal_rank_fusion(r, k=1000)[1].score)
    assert gap_large < gap_small


def test_ties_are_broken_deterministically_and_top_n_applies():
    fused = reciprocal_rank_fusion({"bm25": rank("b"), "vector": rank("a")}, top_n=1)
    assert [h.chunk_id for h in fused] == ["a"]


def test_input_hits_are_not_mutated_and_empty_input_is_fine():
    original = rank("a")
    reciprocal_rank_fusion({"bm25": original})
    assert original[0].score == 1.0 and original[0].signals == {}
    assert reciprocal_rank_fusion({"bm25": [], "vector": []}) == []


def test_invalid_k_is_rejected():
    with pytest.raises(ValueError):
        reciprocal_rank_fusion({"bm25": rank("a")}, k=0)
