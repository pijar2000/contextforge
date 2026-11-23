"""Incremental ingestion.

Lifecycle of a document (see docs/ingestion-pipeline.md):

  scan -> detect (new / modified / unchanged / deleted) -> extract -> normalize -> chunk
       -> embed -> index (Qdrant + OpenSearch) -> validate -> commit (PostgreSQL)

Two version pointers on the document row make this safe to interrupt:
  current_version  the newest version seen on the source
  indexed_version  the newest version fully present in both indexes
Search only trusts `indexed_version`, and old chunks are deleted only after the new version
has been written to both indexes and the counts verified. A crash at any point therefore leaves
either the old version served or the new one, never a mix, and the next run retries.
"""

import functools
import json
import logging
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from contextforge.access_control.policy import PolicyResolver
from contextforge.chunking import ChunkingConfig, DocumentContext, chunk_document
from contextforge.common.hashing import document_id_for, sha256_bytes
from contextforge.common.logging import bind_context, log_fields
from contextforge.common.metrics import Metrics
from contextforge.common.models import ParsedDocument
from contextforge.connectors.base import SourceConnector, SourceFile
from contextforge.embeddings import Embedder
from contextforge.indexing.base import KeywordIndex, VectorIndex
from contextforge.ingestion.workitem import COMMITTED, EMPTY, FAILED, PENDING, WorkItem
from contextforge.normalization.normalize import normalize_document
from contextforge.parsing import ParsingError, parse_document
from contextforge.storage import Repository, session_scope
from contextforge.storage.models import Document, DocumentVersion, utcnow
from contextforge.storage.object_store import ObjectStore, object_key

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    pass


@dataclass
class DetectionResult:
    items: list[WorkItem] = field(default_factory=list)
    deleted_document_ids: list[str] = field(default_factory=list)
    scanned: int = 0
    skipped: int = 0


@dataclass
class RunSummary:
    run_id: str
    tenant_id: str
    scanned: int = 0
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    empty: int = 0
    deleted: int = 0
    chunks_created: int = 0
    embeddings_generated: int = 0
    duration_seconds: float = 0.0
    errors: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _stage(allowed: tuple[str, ...] = (PENDING,)):
    """Run a stage only for items still in an allowed state; convert exceptions to failures.

    Because each stage is a no-op for failed items, the same methods can be chained in-process or
    scheduled one by one from Airflow.
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(self, item: WorkItem, *args, **kwargs):
            if item.status not in allowed:
                return item
            try:
                fn(self, item, *args, **kwargs)
            except Exception as exc:
                self.fail(item, fn.__name__, exc)
            return item

        return wrapper

    return decorator


class IngestionPipeline:
    def __init__(
        self,
        session_factory,
        object_store: ObjectStore,
        embedder: Embedder,
        vector_index: VectorIndex,
        keyword_index: KeywordIndex,
        policy: PolicyResolver,
        chunking: ChunkingConfig,
        metrics: Metrics | None = None,
    ):
        self.sf = session_factory
        self.objects = object_store
        self.embedder = embedder
        self.vectors = vector_index
        self.keywords = keyword_index
        self.policy = policy
        self.chunking = chunking
        self.metrics = metrics or Metrics()

    # ------------------------------------------------------------------ detection
    def detect(
        self,
        connector: SourceConnector,
        tenant_id: str,
        run_id: str,
        force: bool = False,
    ) -> DetectionResult:
        result = DetectionResult()
        seen: set[str] = set()
        with session_scope(self.sf) as session:
            repo = Repository(session)
            for file in connector.scan():
                result.scanned += 1
                doc_id = document_id_for(tenant_id, file.source_name, file.relative_path)
                seen.add(doc_id)
                item = self._classify(repo, file, tenant_id, doc_id, run_id, force)
                if item is None:
                    result.skipped += 1
                else:
                    result.items.append(item)

            active = repo.active_documents(tenant_id, connector.source_name)
            prefix = getattr(connector, "scope_prefix", None)
            if prefix:
                active = [d for d in active if d.source_path.startswith(prefix)]
            missing = [d.document_id for d in active if d.document_id not in seen]
            if missing and result.scanned == 0 and not force:
                raise PipelineError(
                    f"source returned no files but {len(missing)} documents are indexed; refusing "
                    "to delete them. Check the source mount, or re-run with force=True."
                )
            result.deleted_document_ids = missing
        self.metrics.inc("documents_scanned", result.scanned)
        self.metrics.inc("documents_skipped", result.skipped)
        return result

    def _classify(
        self, repo: Repository, file: SourceFile, tenant_id: str, doc_id: str, run_id: str, force: bool
    ) -> WorkItem | None:
        policy = self.policy.resolve(file.relative_path)
        groups = list(policy.allowed_groups)
        doc = repo.get_document(doc_id)

        if doc is None:
            action, version = "new", 1
            doc = Document(
                document_id=doc_id,
                tenant_id=tenant_id,
                source_name=file.source_name,
                source_path=file.relative_path,
                file_name=file.file_name,
                file_type=file.file_type,
                content_hash=file.content_hash,
                current_version=1,
                status="processing",
                owner_id=policy.owner_id,
                allowed_groups=groups,
            )
            repo.s.add(doc)
        else:
            acl_changed = doc.owner_id != policy.owner_id or sorted(doc.allowed_groups or []) != sorted(groups)
            unchanged = doc.content_hash == file.content_hash and doc.status != "deleted"
            if force:
                action, version = "reindex", doc.current_version
            elif doc.status == "deleted":
                action, version = "restored", doc.current_version + 1
            elif not unchanged:
                action, version = "modified", doc.current_version + 1
            elif doc.status in ("failed", "processing", "pending"):
                action, version = "retry", doc.current_version
            elif acl_changed:
                action, version = "acl_update", doc.current_version
            else:
                return None  # indexed or empty, same content, same permissions
            doc.deleted_at = None

        doc.file_name, doc.file_type = file.file_name, file.file_type
        doc.source_path, doc.size_bytes, doc.modified_at = file.relative_path, file.size_bytes, file.modified_at
        doc.content_hash, doc.current_version = file.content_hash, version
        doc.owner_id, doc.allowed_groups = policy.owner_id, groups
        doc.status = "processing"

        row = repo.get_version(doc_id, version)
        key = object_key(tenant_id, doc_id, version, file.file_name)
        if row is None:
            repo.s.add(
                DocumentVersion(
                    document_id=doc_id,
                    version=version,
                    content_hash=file.content_hash,
                    object_key=key,
                    status="pending",
                    run_id=run_id,
                )
            )
        else:
            row.status, row.error, row.run_id, row.content_hash = "pending", None, run_id, file.content_hash

        return WorkItem(
            document_id=doc_id,
            tenant_id=tenant_id,
            version=version,
            action=action,
            source_name=file.source_name,
            source_path=file.relative_path,
            file_name=file.file_name,
            file_type=file.file_type,
            size_bytes=file.size_bytes,
            modified_at=file.modified_at.isoformat(),
            content_hash=file.content_hash,
            absolute_path=file.absolute_path,
            owner_id=policy.owner_id,
            allowed_groups=groups,
            object_key=key,
        )

    # ------------------------------------------------------------------ stages
    @_stage()
    def extract(self, item: WorkItem, data: bytes | None = None, connector: SourceConnector | None = None):
        """Read the file once, archive the exact bytes, then parse those same bytes.

        `data` is supplied only when re-indexing from the archive; bytes read from the source are
        checked against the hash recorded at scan time, so a file edited mid-run is retried
        instead of being stored under the wrong hash.
        """
        if data is None:
            if connector is not None:
                data = connector.read(item.to_source_file())
            else:
                data = Path(item.absolute_path).read_bytes()
            if sha256_bytes(data) != item.content_hash:
                raise PipelineError("file changed while it was being ingested; it will be retried")
            self.objects.put(item.object_key, data)
        parsed = parse_document(data, item.file_type)
        item.title, item.page_count, item.sections = parsed.title, parsed.page_count, parsed.sections

    @_stage()
    def normalize(self, item: WorkItem):
        doc = normalize_document(
            ParsedDocument(item.title, item.sections, item.page_count), item.file_type
        )
        item.title, item.sections = doc.title, doc.sections
        if doc.is_empty:
            item.status = EMPTY

    @_stage()
    def chunk(self, item: WorkItem):
        ctx = DocumentContext(
            document_id=item.document_id,
            version=item.version,
            source_path=item.source_path,
            tenant_id=item.tenant_id,
            owner_id=item.owner_id,
            allowed_groups=tuple(item.allowed_groups),
        )
        doc = ParsedDocument(item.title, item.sections, item.page_count)
        item.chunks = chunk_document(doc, ctx, self.chunking)
        if not item.chunks:
            item.status = EMPTY
        self.metrics.inc("chunks_created", len(item.chunks))

    @_stage()
    def embed(self, item: WorkItem):
        item.vectors = self.embedder.embed_documents([c.embedding_text for c in item.chunks])
        self.metrics.inc("embeddings_generated", len(item.chunks))

    @_stage()
    def index_vector(self, item: WorkItem):
        self.vectors.upsert(item.chunks, item.vectors)

    @_stage()
    def index_keyword(self, item: WorkItem):
        self.keywords.upsert(item.chunks)

    @_stage()
    def validate(self, item: WorkItem):
        expected = len(item.chunks)
        found_vec = self.vectors.count(item.document_id, item.version)
        found_kw = self.keywords.count(item.document_id, item.version)
        if found_vec != expected or found_kw != expected:
            raise PipelineError(
                f"index mismatch for {item.source_path} v{item.version}: expected {expected} "
                f"chunks, vector index has {found_vec}, keyword index has {found_kw}"
            )

    @_stage(allowed=(PENDING, EMPTY))
    def commit(self, item: WorkItem):
        """Switch the document to the new version and drop everything older."""
        if item.status == EMPTY:
            self.vectors.delete_document(item.document_id)
            self.keywords.delete_document(item.document_id)
            keep: int | None = None
        else:
            self.vectors.delete_document(item.document_id, keep_version=item.version)
            self.keywords.delete_document(item.document_id, keep_version=item.version)
            keep = item.version

        with session_scope(self.sf) as session:
            repo = Repository(session)
            doc = repo.get_document(item.document_id)
            if keep is None:
                repo.delete_chunks(item.document_id)
            else:
                repo.replace_chunks(item.document_id, item.version, item.chunks)
                repo.delete_chunks(item.document_id, keep_version=item.version)
            for row in repo.list_versions(item.document_id):
                if row.version != item.version and row.status in ("indexed", "empty", "pending"):
                    row.status = "superseded"
            row = repo.get_version(item.document_id, item.version)
            row.status = "empty" if item.status == EMPTY else "indexed"
            row.chunk_count = len(item.chunks)
            row.page_count = item.page_count
            row.chunk_strategy = self.chunking.strategy
            row.embedding_model = self.embedder.name
            row.indexed_at = utcnow()
            row.error = "No extractable text (scanned PDF? OCR is not enabled)." if item.status == EMPTY else None
            doc.title = item.title
            doc.indexed_version = None if item.status == EMPTY else item.version
            doc.status = "empty" if item.status == EMPTY else "indexed"
            doc.last_error = row.error
            doc.last_ingested_at = utcnow()
        item.status = COMMITTED if item.status != EMPTY else EMPTY

    def fail(self, item: WorkItem, stage: str, exc: Exception) -> None:
        if isinstance(exc, ParsingError):
            error = {"stage": stage, **exc.to_dict(), "type": "ParsingError"}
        else:
            error = {
                "stage": stage,
                "type": type(exc).__name__,
                "message": str(exc),
                "detail": traceback.format_exc(limit=6)[-1500:],
            }
        item.status, item.error = FAILED, error
        log_fields(logger, logging.ERROR, "document failed", document=item.source_path, **error)
        self.metrics.inc("documents_failed", stage=stage)
        try:
            with session_scope(self.sf) as session:
                repo = Repository(session)
                doc = repo.get_document(item.document_id)
                row = repo.get_version(item.document_id, item.version)
                if doc is not None:
                    doc.status = "failed"
                    doc.last_error = json.dumps(error)
                    doc.last_ingested_at = utcnow()
                if row is not None:
                    row.status, row.error = "failed", json.dumps(error)
        except Exception:
            logger.exception("could not persist failure for %s", item.source_path)

    # ------------------------------------------------------------------ composition
    def process(self, item: WorkItem, data: bytes | None = None, connector=None) -> WorkItem:
        self.extract(item, data=data, connector=connector)
        self.normalize(item)
        self.chunk(item)
        self.embed(item)
        self.index_vector(item)
        self.index_keyword(item)
        self.validate(item)
        self.commit(item)
        return item

    def delete_documents(self, document_ids: list[str]) -> int:
        count = 0
        for doc_id in document_ids:
            # Index removal comes first: if it fails the document stays visible and is retried.
            self.vectors.delete_document(doc_id)
            self.keywords.delete_document(doc_id)
            with session_scope(self.sf) as session:
                repo = Repository(session)
                doc = repo.get_document(doc_id)
                if doc is None or doc.status == "deleted":
                    continue
                repo.delete_chunks(doc_id)
                doc.status, doc.deleted_at, doc.indexed_version = "deleted", utcnow(), None
                for row in repo.list_versions(doc_id):
                    if row.status in ("indexed", "pending", "empty"):
                        row.status = "superseded"
                count += 1
        return count

    def reindex_document(self, document_id: str, run_id: str | None = None) -> WorkItem:
        """Rebuild a document's chunks and index entries from the archived raw file."""
        run_id = run_id or uuid.uuid4().hex[:12]
        with session_scope(self.sf) as session:
            repo = Repository(session)
            doc = repo.get_document(document_id)
            if doc is None or doc.status == "deleted":
                raise KeyError(document_id)
            row = repo.get_version(document_id, doc.current_version)
            if row is None or not row.object_key:
                raise PipelineError("no archived raw file for this document version")
            policy = self.policy.resolve(doc.source_path)
            doc.owner_id, doc.allowed_groups = policy.owner_id, list(policy.allowed_groups)
            doc.status, row.status, row.error, row.run_id = "processing", "pending", None, run_id
            item = WorkItem(
                document_id=doc.document_id,
                tenant_id=doc.tenant_id,
                version=doc.current_version,
                action="reindex",
                source_name=doc.source_name,
                source_path=doc.source_path,
                file_name=doc.file_name,
                file_type=doc.file_type,
                size_bytes=doc.size_bytes,
                modified_at=(doc.modified_at or utcnow()).isoformat(),
                content_hash=doc.content_hash,
                absolute_path="",
                owner_id=doc.owner_id,
                allowed_groups=list(doc.allowed_groups),
                object_key=row.object_key,
            )
        try:
            data = self.objects.get(item.object_key)
        except Exception as exc:
            self.fail(item, "extract", exc)
            return item
        return self.process(item, data=data)

    # ------------------------------------------------------------------ runs
    def summarize(self, run_id: str, tenant_id: str, detection: DetectionResult, items: list[WorkItem],
                  deleted: int, started: float) -> RunSummary:
        summary = RunSummary(run_id=run_id, tenant_id=tenant_id)
        summary.scanned, summary.skipped = detection.scanned, detection.skipped
        summary.deleted = deleted
        for item in items:
            if item.status == FAILED:
                summary.failed += 1
                summary.errors.append({"source_path": item.source_path, **(item.error or {})})
            elif item.status == EMPTY:
                summary.empty += 1
            elif item.status == COMMITTED:
                summary.processed += 1
                summary.chunks_created += len(item.chunks)
                summary.embeddings_generated += len(item.chunks)
        summary.duration_seconds = round(time.monotonic() - started, 3)
        return summary

    def record_run(self, summary: RunSummary, trigger: str, started_at: datetime) -> None:
        with session_scope(self.sf) as session:
            repo = Repository(session)
            run = repo.get_run(summary.run_id) or repo.create_run(summary.run_id, summary.tenant_id, trigger)
            run.status = "failed" if summary.failed else "succeeded"
            run.started_at, run.finished_at = started_at, utcnow()
            run.docs_scanned, run.docs_processed = summary.scanned, summary.processed
            run.docs_skipped, run.docs_failed, run.docs_deleted = summary.skipped, summary.failed, summary.deleted
            run.chunks_created, run.embeddings_generated = summary.chunks_created, summary.embeddings_generated
            run.duration_seconds = summary.duration_seconds
            run.details = {"empty": summary.empty, "errors": summary.errors[:50]}
        self.metrics.observe("indexing_duration_seconds", summary.duration_seconds)
        self.metrics.inc("documents_processed", summary.processed)

    def run(
        self,
        connector: SourceConnector,
        tenant_id: str,
        force: bool = False,
        trigger: str = "manual",
        run_id: str | None = None,
    ) -> RunSummary:
        run_id = run_id or uuid.uuid4().hex[:12]
        bind_context(run_id=run_id)
        started, started_at = time.monotonic(), utcnow()
        detection = self.detect(connector, tenant_id, run_id, force=force)
        items = [self.process(item, connector=connector) for item in detection.items]
        deleted = self.delete_documents(detection.deleted_document_ids)
        summary = self.summarize(run_id, tenant_id, detection, items, deleted, started)
        self.record_run(summary, trigger, started_at)
        log_fields(logger, logging.INFO, "ingestion run finished", **summary.to_dict())
        return summary
