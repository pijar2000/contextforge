"""End-to-end ingestion against the local backend (SQLite + in-memory indexes)."""

import pytest

pytest.importorskip("fitz")  # the sample corpus contains PDFs

from sqlalchemy import select  # noqa: E402

from contextforge.storage import Repository, session_scope  # noqa: E402
from contextforge.storage.models import Document  # noqa: E402
from tests.conftest import supported_files  # noqa: E402


def doc_by_path(services, path):
    with session_scope(services.session_factory) as s:
        return s.scalars(select(Document).where(Document.source_path == path)).one()


def search_paths(services, user, query, mode="hybrid", k=10):
    return [h.source_path for h in services.retriever.search(query, user, mode, k).hits]


def test_first_ingest_processes_every_supported_file(services, run_ingest, source_dir):
    summary = run_ingest()
    assert summary.scanned == len(supported_files(source_dir))
    assert summary.failed == 0 and summary.processed == summary.scanned
    assert summary.chunks_created == services.vector_index.count() == services.keyword_index.count()


def test_second_run_without_changes_does_no_work(services, run_ingest):
    first = run_ingest()
    before = services.vector_index.count()
    second = run_ingest()
    assert second.skipped == first.scanned and second.processed == 0
    assert services.vector_index.count() == services.keyword_index.count() == before
    assert second.chunks_created == 0 and second.embeddings_generated == 0


def test_force_reindex_is_idempotent(services, run_ingest):
    run_ingest()
    before = (services.vector_index.count(), services.keyword_index.count())
    run_ingest(force=True)
    run_ingest(force=True)
    assert (services.vector_index.count(), services.keyword_index.count()) == before


def test_modified_document_gets_new_version_and_old_content_disappears(
    services, run_ingest, source_dir, users
):
    run_ingest()
    doc = doc_by_path(services, "product/hx200-gripper-manual.md")
    path = source_dir / "product" / "hx200-gripper-manual.md"
    path.write_text(path.read_text() + "\n## Warranty\n\nThe HX-200 warranty lasts 36 months.\n")

    summary = run_ingest()
    assert summary.processed == 1 and summary.skipped == summary.scanned - 1

    updated = doc_by_path(services, "product/hx200-gripper-manual.md")
    assert (updated.current_version, updated.indexed_version) == (2, 2)
    assert services.vector_index.count(doc.document_id, 1) == 0
    assert services.keyword_index.count(doc.document_id, 1) == 0
    assert services.keyword_index.count(doc.document_id, 2) > 0
    assert "product/hx200-gripper-manual.md" in search_paths(
        services, users["erin"], '"warranty lasts 36 months"', "bm25"
    )
    with session_scope(services.session_factory) as s:
        statuses = {v.version: v.status for v in Repository(s).list_versions(doc.document_id)}
    assert statuses == {1: "superseded", 2: "indexed"}


def test_deleted_file_is_removed_from_search(services, run_ingest, source_dir, users):
    run_ingest()
    assert "operations/warehouse-safety-procedure.txt" in search_paths(
        services, users["dave"], "forklift speed limit", "bm25"
    )
    doc = doc_by_path(services, "operations/warehouse-safety-procedure.txt")
    (source_dir / "operations" / "warehouse-safety-procedure.txt").unlink()

    summary = run_ingest()
    assert summary.deleted == 1
    for mode in ("bm25", "vector", "hybrid"):
        assert "operations/warehouse-safety-procedure.txt" not in search_paths(
            services, users["alice"], "forklift speed limit", mode
        )
    assert services.vector_index.count(doc.document_id) == 0
    assert doc_by_path(services, "operations/warehouse-safety-procedure.txt").status == "deleted"


def test_restored_file_returns_as_a_new_version(services, run_ingest, source_dir, users):
    run_ingest()
    target = source_dir / "operations" / "warehouse-safety-procedure.txt"
    content = target.read_bytes()
    target.unlink()
    run_ingest()
    target.write_bytes(content)
    run_ingest()
    doc = doc_by_path(services, "operations/warehouse-safety-procedure.txt")
    assert doc.status == "indexed" and doc.indexed_version == doc.current_version == 2
    assert search_paths(services, users["dave"], "forklift speed limit", "bm25")


def test_empty_source_does_not_wipe_the_index(services, run_ingest, source_dir):
    from contextforge.ingestion.pipeline import PipelineError

    run_ingest()
    for path in supported_files(source_dir):
        path.unlink()
    with pytest.raises(PipelineError):
        run_ingest()
    assert services.vector_index.count() > 0


def test_corrupted_file_is_recorded_not_skipped_and_recovers_when_fixed(
    services, run_ingest, source_dir
):
    bad = source_dir / "engineering" / "broken.docx"
    bad.write_bytes(b"definitely not a docx")
    summary = run_ingest()
    assert summary.failed == 1 and summary.processed == summary.scanned - 1
    assert summary.errors[0]["source_path"] == "engineering/broken.docx"
    assert summary.errors[0]["parser"] == "docx"

    doc = doc_by_path(services, "engineering/broken.docx")
    assert doc.status == "failed" and "docx" in doc.last_error and doc.indexed_version is None
    assert services.vector_index.count(doc.document_id) == 0

    assert run_ingest().failed == 1  # unchanged bad file is retried, and fails again, visibly

    from docx import Document as Docx

    fixed = Docx()
    fixed.add_heading("Recovered", level=1)
    fixed.add_paragraph("now valid content")
    bad.unlink()
    fixed.save(bad)
    assert run_ingest().failed == 0
    doc = doc_by_path(services, "engineering/broken.docx")
    assert doc.status == "indexed" and doc.current_version == 2


def test_zero_byte_file_is_marked_empty_and_not_reprocessed(services, run_ingest, source_dir):
    (source_dir / "engineering" / "blank.txt").write_bytes(b"")
    assert run_ingest().empty == 1
    doc = doc_by_path(services, "engineering/blank.txt")
    assert doc.status == "empty" and "No extractable text" in doc.last_error
    again = run_ingest()
    assert again.empty == 0 and again.processed == 0


def test_interrupted_indexing_keeps_serving_old_version_then_recovers(
    services, run_ingest, source_dir, users, monkeypatch
):
    run_ingest()
    doc = doc_by_path(services, "policies/remote-work-policy.md")
    target = source_dir / "policies" / "remote-work-policy.md"
    target.write_text(target.read_text().replace("up to 3 days per week", "up to 4 days per week"))

    real_upsert = services.keyword_index.upsert

    def exploding_upsert(chunks):
        raise RuntimeError("opensearch unavailable")

    monkeypatch.setattr(services.keyword_index, "upsert", exploding_upsert)
    summary = run_ingest()
    assert summary.failed == 1
    failed = doc_by_path(services, "policies/remote-work-policy.md")
    assert failed.status == "failed" and failed.indexed_version == 1 and failed.current_version == 2

    # vector index already holds v2 chunks, but only the indexed version may be returned
    erin = users["erin"]
    for mode in ("vector", "bm25", "hybrid"):
        hits = services.retriever.search("remote work days per week", erin, mode, 10).hits
        assert hits and {h.document_version for h in hits if h.document_id == doc.document_id} <= {1}

    monkeypatch.setattr(services.keyword_index, "upsert", real_upsert)
    assert run_ingest().processed == 1
    healed = doc_by_path(services, "policies/remote-work-policy.md")
    assert (healed.status, healed.indexed_version) == ("indexed", 2)
    assert services.vector_index.count(doc.document_id, 1) == 0
    assert services.keyword_index.count(doc.document_id, 1) == 0


def test_acl_change_updates_index_payloads(services, run_ingest, tmp_path, source_dir, users, connector):
    from contextforge.access_control.policy import AccessPolicy, PolicyResolver

    run_ingest()
    assert search_paths(services, users["erin"], "travel meal allowance", "bm25")
    services.pipeline.policy = PolicyResolver(
        AccessPolicy("system", ("administrator",)),
        [("policies/travel*", AccessPolicy("finance", ("administrator",)))],
    )
    summary = run_ingest()
    assert summary.processed >= 1
    assert search_paths(services, users["erin"], "travel meal allowance", "bm25") == []


def test_pdf_chunks_keep_page_numbers(services, run_ingest, users):
    run_ingest()
    hits = services.retriever.search("2,000 operating hours hydraulic fluid", users["alice"], "bm25", 3).hits
    assert hits[0].source_path == "product/hx200-maintenance-guide.pdf"
    assert hits[0].page_number == 2
