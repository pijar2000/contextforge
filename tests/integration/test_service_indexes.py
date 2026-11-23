"""Adapter tests against real Qdrant and OpenSearch. Run with `make up` (or CI service
containers) and `pytest -m integration tests/integration/test_service_indexes.py`."""

import os
import uuid

import pytest

from contextforge.embeddings import HashingEmbedder
from tests.unit.helpers import ADMIN, EMP, ENG, make_chunk

pytestmark = pytest.mark.integration

QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
OPENSEARCH_URL = os.environ.get("OPENSEARCH_URL", "http://localhost:9200")


@pytest.fixture
def qdrant():
    from contextforge.indexing.qdrant_index import QdrantVectorIndex

    index = QdrantVectorIndex(QDRANT_URL, f"test_{uuid.uuid4().hex[:8]}", 64)
    index.ensure()
    yield index
    index.client.delete_collection(index.collection)


@pytest.fixture
def opensearch():
    from contextforge.indexing.opensearch_index import OpenSearchKeywordIndex

    index = OpenSearchKeywordIndex(OPENSEARCH_URL, f"test-{uuid.uuid4().hex[:8]}")
    index.ensure()
    yield index
    index.client.indices.delete(index=index.index)


def chunks():
    return [
        make_chunk(index=0, text="gateway returns ERR-4021 when rate limit is exceeded", groups=("engineering",)),
        make_chunk(index=1, text="salary bands for executives", groups=("administrator",)),
    ]


def test_qdrant_search_filters_upserts_idempotently_and_deletes(qdrant):
    emb = HashingEmbedder(64)
    cs = chunks()
    vectors = emb.embed_documents([c.text for c in cs])
    qdrant.upsert(cs, vectors)
    qdrant.upsert(cs, vectors)
    assert qdrant.count("d1") == 2
    q = emb.embed_query("salary bands executives")
    assert [h.chunk_index for h in qdrant.search(q, 5, ADMIN)][0] == 1
    assert all(h.chunk_index != 1 for h in qdrant.search(q, 5, ENG))
    assert qdrant.search(q, 5, EMP) == []
    qdrant.delete_document("d1", keep_version=2)
    assert qdrant.count("d1") == 0


def test_opensearch_bm25_phrase_filters_and_deletes(opensearch):
    opensearch.upsert(chunks())
    opensearch.upsert(chunks())
    assert opensearch.count("d1") == 2
    assert opensearch.search("ERR-4021", 5, ENG)[0].chunk_index == 0
    assert opensearch.search('"rate limit is exceeded"', 5, ENG)
    assert opensearch.search('"exceeded rate limit"', 5, ENG) == []
    assert opensearch.search("salary", 5, ENG) == []
    assert opensearch.search("salary", 5, ADMIN)
    opensearch.delete_document("d1")
    assert opensearch.count("d1") == 0
