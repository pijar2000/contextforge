import pytest

pytest.importorskip("fitz")

from fastapi.testclient import TestClient  # noqa: E402

from contextforge.api import create_app  # noqa: E402
from tests.conftest import KEYS, supported_files  # noqa: E402

ADMIN = {"X-API-Key": KEYS["alice"]}


@pytest.fixture
def client(services):
    return TestClient(create_app(services, services.settings))


def test_health_reports_each_dependency(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and set(body["checks"]) == {"postgres", "object_store", "qdrant", "opensearch"}


def test_ingest_endpoint_indexes_documents_and_is_incremental(client, source_dir):
    first = client.post("/documents/ingest", headers=ADMIN, json={}).json()
    assert first["processed"] == len(supported_files(source_dir)) and first["failed"] == 0
    second = client.post("/documents/ingest", headers=ADMIN, json={}).json()
    assert second["processed"] == 0 and second["skipped"] == first["scanned"]


def test_ingest_subdirectory_does_not_delete_other_documents(client):
    client.post("/documents/ingest", headers=ADMIN, json={})
    r = client.post("/documents/ingest", headers=ADMIN, json={"source_path": "policies"}).json()
    assert r["deleted"] == 0
    assert client.get("/documents", headers=ADMIN, params={"limit": 1}).json()["total"] > 5


def test_ingest_rejects_path_traversal_and_missing_directories(client):
    assert client.post("/documents/ingest", headers=ADMIN, json={"source_path": "../.."}).status_code == 400
    assert client.post("/documents/ingest", headers=ADMIN, json={"source_path": "nope"}).status_code == 404


def test_document_listing_is_paginated(client):
    client.post("/documents/ingest", headers=ADMIN, json={})
    page1 = client.get("/documents", headers=ADMIN, params={"limit": 5, "offset": 0}).json()
    page2 = client.get("/documents", headers=ADMIN, params={"limit": 5, "offset": 5}).json()
    assert len(page1["items"]) == 5 and page1["total"] >= 10
    assert {d["document_id"] for d in page1["items"]}.isdisjoint({d["document_id"] for d in page2["items"]})
    assert client.get("/documents", headers=ADMIN, params={"limit": 0}).status_code == 422


def test_document_detail_includes_versions(client):
    client.post("/documents/ingest", headers=ADMIN, json={})
    doc = client.get("/documents", headers=ADMIN, params={"limit": 1}).json()["items"][0]
    detail = client.get(f"/documents/{doc['document_id']}", headers=ADMIN).json()
    assert detail["versions"][0]["status"] == "indexed" and detail["versions"][0]["chunk_count"] > 0


def test_search_validates_requests(client):
    for body in ({"query": ""}, {"query": "x", "top_k": 0}, {"query": "x", "mode": "magic"}):
        assert client.post("/search", headers=ADMIN, json=body).status_code == 422


def test_search_returns_scores_signals_and_timings(client):
    client.post("/documents/ingest", headers=ADMIN, json={})
    body = client.post("/search", headers=ADMIN, json={"query": "ERR-4021", "mode": "hybrid", "rerank": True}).json()
    top = body["hits"][0]
    assert top["source_path"] == "engineering/api-gateway-runbook.md"
    assert {"bm25_rank", "rrf_score", "rerank_score"} <= set(top["signals"])
    assert {"bm25_ms", "vector_ms", "fusion_ms", "rerank_ms", "total_ms"} <= set(body["timings_ms"])


def test_chat_without_llm_returns_cited_excerpts(client):
    client.post("/documents/ingest", headers=ADMIN, json={})
    body = client.post("/chat", headers=ADMIN, json={"question": "What does ERR-4021 mean?"}).json()
    assert body["mode"] == "extractive" and body["answer"] is None
    assert body["citations"][0]["source_path"] == "engineering/api-gateway-runbook.md"
    assert "ERR-4021" in body["excerpts"][0]["excerpt"]


def test_chat_reports_insufficient_evidence_for_unrelated_questions(client):
    client.post("/documents/ingest", headers=ADMIN, json={})
    body = client.post("/chat", headers=ADMIN, json={"question": "zzzqqq xylophone"}).json()
    assert body["mode"] == "insufficient" and body["citations"] == []


def test_reindex_and_delete_endpoints(client):
    client.post("/documents/ingest", headers=ADMIN, json={})
    docs = client.get("/documents", headers=ADMIN, params={"limit": 200}).json()["items"]
    doc = next(d for d in docs if d["source_path"] == "policies/travel-and-expense-policy.md")
    r = client.post(f"/documents/{doc['document_id']}/reindex", headers=ADMIN).json()
    assert r["status"] == "committed" and r["chunks"] > 0
    assert client.delete(f"/documents/{doc['document_id']}", headers=ADMIN).status_code == 204
    assert client.get(f"/documents/{doc['document_id']}", headers=ADMIN).status_code == 404
    hits = client.post("/search", headers=ADMIN, json={"query": "meal allowance business trips"}).json()["hits"]
    assert all(h["source_path"] != "policies/travel-and-expense-policy.md" for h in hits)
    assert client.delete(f"/documents/{doc['document_id']}", headers=ADMIN).status_code == 404


def test_metrics_endpoint_exposes_counters(client):
    client.post("/documents/ingest", headers=ADMIN, json={})
    client.post("/search", headers=ADMIN, json={"query": "gateway"})
    text = client.get("/metrics").text
    assert "contextforge_documents_scanned_total" in text
    assert "contextforge_search_requests_total" in text
    assert "contextforge_search_latency_ms_count" in text


def test_evaluation_results_404_until_a_report_exists(client):
    assert client.get("/evaluation/results", headers=ADMIN).status_code == 404


def test_openapi_documents_the_main_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    for p in ("/health", "/documents", "/documents/{document_id}", "/search", "/chat", "/metrics",
              "/documents/ingest", "/evaluation/results", "/documents/{document_id}/reindex"):
        assert p in paths
