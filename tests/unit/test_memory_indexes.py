import numpy as np

from contextforge.embeddings import HashingEmbedder
from contextforge.indexing.memory import InMemoryKeywordIndex, InMemoryVectorIndex

from .helpers import ADMIN, EMP, ENG, OTHER_TENANT, make_chunk


def kw_index():
    idx = InMemoryKeywordIndex()
    idx.upsert([
        make_chunk(index=0, text="The gateway returns ERR-4021 when the rate limit is exceeded"),
        make_chunk(index=1, text="Rotate the API key every ninety days", title="Keys"),
        make_chunk(doc="d2", index=0, text="Rate limit policy for partners and rate limit tiers"),
    ])
    return idx


def test_bm25_finds_exact_code_and_ranks_by_relevance():
    hits = kw_index().search("ERR-4021", 5, ADMIN)
    assert [h.chunk_id.split(":")[-1] for h in hits] == ["00000"] and hits[0].document_id == "d1"


def test_bm25_prefers_chunk_with_more_matching_terms():
    hits = kw_index().search("rate limit", 5, ADMIN)
    assert hits[0].document_id == "d2"


def test_bm25_quoted_phrase_is_mandatory():
    idx = kw_index()
    assert idx.search('"rate limit is exceeded"', 5, ADMIN)[0].document_id == "d1"
    assert idx.search('"limit rate"', 5, ADMIN) == []


def test_bm25_section_title_counts():
    assert kw_index().search("keys", 5, ADMIN)[0].section_title == "Keys"


def test_bm25_no_match_returns_nothing():
    assert kw_index().search("zebra", 5, ADMIN) == []


def test_keyword_index_filters_by_group_tenant_and_owner():
    idx = InMemoryKeywordIndex()
    idx.upsert([make_chunk(text="secret plan", groups=("administrator",), owner="boss")])
    assert idx.search("secret", 5, ADMIN)
    assert idx.search("secret", 5, ENG) == []
    assert idx.search("secret", 5, EMP) == []
    assert idx.search("secret", 5, OTHER_TENANT) == []
    owner_view = ENG.__class__("acme", "boss", ("general_employee",))
    assert idx.search("secret", 5, owner_view)


def test_upsert_is_idempotent_and_delete_removes_old_versions_only():
    idx = InMemoryKeywordIndex()
    v1 = make_chunk(version=1, text="alpha beta")
    v2 = make_chunk(version=2, text="alpha gamma")
    idx.upsert([v1])
    idx.upsert([v1])
    assert idx.count("d1") == 1
    idx.upsert([v2])
    idx.delete_document("d1", keep_version=2)
    assert idx.count("d1", 1) == 0 and idx.count("d1", 2) == 1
    assert [h.document_version for h in idx.search("alpha", 5, ADMIN)] == [2]
    idx.delete_document("d1")
    assert idx.count() == 0 and idx.search("alpha", 5, ADMIN) == []


def test_version_filter():
    idx = InMemoryKeywordIndex()
    idx.upsert([make_chunk(version=1, text="alpha"), make_chunk(version=2, text="alpha")])
    assert [h.document_version for h in idx.search("alpha", 5, ADMIN, document_version=1)] == [1]


def vec_index():
    emb = HashingEmbedder(64)
    idx = InMemoryVectorIndex()
    chunks = [
        make_chunk(index=0, text="hydraulic gripper payload limit"),
        make_chunk(index=1, text="remote work policy home office"),
        make_chunk(doc="d2", index=0, text="finance expense report", groups=("administrator",)),
    ]
    idx.upsert(chunks, emb.embed_documents([c.text for c in chunks]))
    return idx, emb


def test_vector_search_returns_nearest_first():
    idx, emb = vec_index()
    hits = idx.search(emb.embed_query("gripper payload"), 3, ADMIN)
    assert hits[0].text.startswith("hydraulic")
    assert hits == sorted(hits, key=lambda h: -h.score)


def test_vector_search_enforces_access_in_the_index():
    idx, emb = vec_index()
    hits = idx.search(emb.embed_query("finance expense report"), 5, ENG)
    assert all(h.document_id != "d2" for h in hits)
    assert idx.search(emb.embed_query("finance expense report"), 5, OTHER_TENANT) == []


def test_vector_top_k_and_deletion():
    idx, emb = vec_index()
    assert len(idx.search(emb.embed_query("policy gripper expense"), 1, ADMIN)) == 1
    idx.delete_document("d1")
    assert idx.count("d1") == 0 and idx.count() == 1


def test_hashing_embedder_is_deterministic_and_normalized():
    emb = HashingEmbedder(64)
    a, b = emb.embed_query("same text"), emb.embed_query("same text")
    assert np.array_equal(a, b) and abs(np.linalg.norm(a) - 1) < 1e-5
    assert emb.embed_documents([]).shape == (0, 64)
