"""Database access used by the pipeline, retrieval validation and the API."""

from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from contextforge.common.models import Chunk
from contextforge.storage.models import (
    ChunkRow,
    Document,
    DocumentVersion,
    IngestionRun,
    utcnow,
)


class Repository:
    def __init__(self, session: Session):
        self.s = session

    # ---- documents
    def get_document(self, document_id: str) -> Document | None:
        return self.s.get(Document, document_id)

    def get_documents(self, ids: list[str]) -> dict[str, Document]:
        if not ids:
            return {}
        rows = self.s.scalars(select(Document).where(Document.document_id.in_(ids))).all()
        return {d.document_id: d for d in rows}

    def list_documents(self, tenant_id: str, status: str | None = None) -> list[Document]:
        stmt = select(Document).where(Document.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(Document.status == status)
        return list(self.s.scalars(stmt.order_by(Document.source_path)))

    def active_documents(self, tenant_id: str, source_name: str) -> list[Document]:
        stmt = select(Document).where(
            Document.tenant_id == tenant_id,
            Document.source_name == source_name,
            Document.status != "deleted",
        )
        return list(self.s.scalars(stmt))

    def get_version(self, document_id: str, version: int) -> DocumentVersion | None:
        return self.s.get(DocumentVersion, (document_id, version))

    def list_versions(self, document_id: str) -> list[DocumentVersion]:
        stmt = select(DocumentVersion).where(DocumentVersion.document_id == document_id)
        return list(self.s.scalars(stmt.order_by(DocumentVersion.version)))

    # ---- chunks
    def replace_chunks(self, document_id: str, version: int, chunks: list[Chunk]) -> None:
        self.s.execute(
            delete(ChunkRow).where(
                ChunkRow.document_id == document_id, ChunkRow.document_version == version
            )
        )
        self.s.add_all(
            ChunkRow(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                document_version=c.document_version,
                chunk_index=c.chunk_index,
                page_number=c.page_number,
                section_title=c.section_title,
                text=c.text,
                char_count=len(c.text),
            )
            for c in chunks
        )

    def delete_chunks(self, document_id: str, keep_version: int | None = None) -> None:
        stmt = delete(ChunkRow).where(ChunkRow.document_id == document_id)
        if keep_version is not None:
            stmt = stmt.where(ChunkRow.document_version != keep_version)
        self.s.execute(stmt)

    def chunks_for_documents(self, document_ids: list[str]) -> list[ChunkRow]:
        """Chunks of each document's *indexed* version only."""
        stmt = (
            select(ChunkRow)
            .join(Document, Document.document_id == ChunkRow.document_id)
            .where(
                ChunkRow.document_id.in_(document_ids),
                ChunkRow.document_version == Document.indexed_version,
            )
            .order_by(ChunkRow.document_id, ChunkRow.chunk_index)
        )
        return list(self.s.scalars(stmt))

    # ---- runs
    def create_run(self, run_id: str, tenant_id: str, trigger: str) -> IngestionRun:
        run = IngestionRun(run_id=run_id, tenant_id=tenant_id, trigger=trigger, status="running")
        self.s.add(run)
        return run

    def get_run(self, run_id: str) -> IngestionRun | None:
        return self.s.get(IngestionRun, run_id)

    def latest_runs(self, tenant_id: str, limit: int = 10) -> list[IngestionRun]:
        stmt = (
            select(IngestionRun)
            .where(IngestionRun.tenant_id == tenant_id)
            .order_by(IngestionRun.started_at.desc())
            .limit(limit)
        )
        return list(self.s.scalars(stmt))

    # ---- statistics
    def stats(self, tenant_id: str) -> dict:
        status_rows = self.s.execute(
            select(Document.status, func.count()).where(Document.tenant_id == tenant_id).group_by(Document.status)
        ).all()
        by_status = {status: count for status, count in status_rows}
        chunk_total = self.s.scalar(
            select(func.count())
            .select_from(ChunkRow)
            .join(Document, Document.document_id == ChunkRow.document_id)
            .where(Document.tenant_id == tenant_id, ChunkRow.document_version == Document.indexed_version)
        )
        indexed_versions = self.s.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.tenant_id == tenant_id, Document.indexed_version.is_not(None))
        )
        last: datetime | None = self.s.scalar(
            select(func.max(Document.last_ingested_at)).where(Document.tenant_id == tenant_id)
        )
        return {
            "documents_total": sum(c for s, c in by_status.items() if s != "deleted"),
            "documents_by_status": by_status,
            "chunks_indexed": int(chunk_total or 0),
            "indexed_document_versions": int(indexed_versions or 0),
            "documents_failed": by_status.get("failed", 0),
            "last_ingestion_at": last.isoformat() if last else None,
        }


def touch(document: Document) -> None:
    document.last_ingested_at = utcnow()
