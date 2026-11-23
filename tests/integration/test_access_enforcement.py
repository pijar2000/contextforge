"""Users must not obtain restricted content through any retrieval path."""

import pytest

pytest.importorskip("fitz")

from fastapi.testclient import TestClient  # noqa: E402

from contextforge.api import create_app  # noqa: E402
from tests.conftest import KEYS  # noqa: E402

SECRET_QUERIES = {
    "salary range for band E3": "150,000",
    "Project Lighthouse acquisition price": "42 million",
}


@pytest.fixture
def client(services, run_ingest):
    run_ingest()
    return TestClient(create_app(services, services.settings))


def h(user):
    return {"X-API-Key": KEYS[user]}


@pytest.mark.parametrize("mode", ["bm25", "vector", "hybrid"])
@pytest.mark.parametrize("rerank", [False, True])
def test_search_never_returns_restricted_documents_to_non_admins(client, mode, rerank):
    for user in ("bob", "carol", "dave", "erin"):
        for query, secret in SECRET_QUERIES.items():
            body = client.post("/search", headers=h(user),
                               json={"query": query, "mode": mode, "top_k": 20, "rerank": rerank}).json()
            assert all(not hit["source_path"].startswith("restricted/") for hit in body["hits"])
            assert secret not in str(body)


def test_administrator_can_retrieve_restricted_documents(client):
    body = client.post("/search", headers=h("alice"),
                       json={"query": "salary range for band E3", "mode": "bm25"}).json()
    assert body["hits"][0]["source_path"] == "restricted/executive-compensation-bands.md"


def test_roadmap_is_visible_to_product_but_not_engineering_or_employees(client):
    def paths(user):
        r = client.post("/search", headers=h(user), json={"query": "HX-300 launch", "mode": "bm25", "top_k": 20})
        return {x["source_path"] for x in r.json()["hits"]}

    assert "product/roadmap-2026.md" in paths("carol")
    assert "product/roadmap-2026.md" not in paths("bob")
    assert "product/roadmap-2026.md" not in paths("erin")


def test_other_tenant_sees_nothing(client):
    r = client.post("/search", headers=h("frank"), json={"query": "gateway rollback", "mode": "hybrid"})
    assert r.json()["hits"] == []
    assert client.get("/documents", headers=h("frank")).json()["total"] == 0


def test_direct_document_lookup_is_authorized_and_does_not_leak_existence(client):
    docs = client.get("/documents", headers=h("alice"), params={"limit": 200}).json()["items"]
    secret = next(d for d in docs if d["source_path"].startswith("restricted/executive"))
    assert client.get(f"/documents/{secret['document_id']}", headers=h("alice")).status_code == 200
    assert client.get(f"/documents/{secret['document_id']}", headers=h("erin")).status_code == 404
    assert client.get("/documents/does-not-exist", headers=h("erin")).status_code == 404
    listed = client.get("/documents", headers=h("erin"), params={"limit": 200}).json()["items"]
    assert all(not d["source_path"].startswith("restricted/") for d in listed)


@pytest.mark.parametrize("question", list(SECRET_QUERIES))
def test_assistant_does_not_expose_restricted_content(client, question):
    r = client.post("/chat", headers=h("erin"), json={"question": question})
    assert r.status_code == 200
    assert SECRET_QUERIES[question] not in str(r.json())
    assert all(not c["source_path"].startswith("restricted/") for c in r.json()["citations"])


def test_stale_index_payload_cannot_bypass_current_database_acl(services, client):
    from sqlalchemy import select

    from contextforge.storage import session_scope
    from contextforge.storage.models import Document

    before = client.post("/search", headers=h("erin"), json={"query": "remote work stipend", "mode": "bm25"}).json()
    assert any(x["source_path"] == "policies/remote-work-policy.md" for x in before["hits"])
    with session_scope(services.session_factory) as s:  # ACL changes in PostgreSQL; indexes not yet updated
        doc = s.scalars(select(Document).where(Document.source_path == "policies/remote-work-policy.md")).one()
        doc.allowed_groups = ["administrator"]
    after = client.post("/search", headers=h("erin"), json={"query": "remote work stipend", "mode": "bm25"}).json()
    assert all(x["source_path"] != "policies/remote-work-policy.md" for x in after["hits"])
    assert after["counts"]["dropped_by_validation"] >= 1


def test_authentication_and_admin_endpoints(client):
    assert client.post("/search", json={"query": "x"}).status_code == 401
    assert client.post("/search", headers={"X-API-Key": "nope"}, json={"query": "x"}).status_code == 401
    assert client.post("/documents/ingest", headers=h("erin"), json={}).status_code == 403
    assert client.get("/stats", headers=h("bob")).status_code == 403
