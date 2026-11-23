from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from contextforge.common.models import Chunk, ParsedSection
from contextforge.connectors.base import SourceFile

# pending   -> work remains
# empty     -> parsed fine but no text (e.g. scanned PDF); committed without chunks
# failed    -> a stage raised; details in `error`
# committed -> finished and visible to search
PENDING, EMPTY, FAILED, COMMITTED = "pending", "empty", "failed", "committed"


@dataclass
class WorkItem:
    document_id: str
    tenant_id: str
    version: int
    action: str  # new | modified | restored | retry | acl_update | reindex
    source_name: str
    source_path: str
    file_name: str
    file_type: str
    size_bytes: int
    modified_at: str
    content_hash: str
    absolute_path: str
    owner_id: str
    allowed_groups: list[str]
    status: str = PENDING
    object_key: str | None = None
    title: str | None = None
    page_count: int | None = None
    sections: list[ParsedSection] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)
    vectors: np.ndarray | None = None
    error: dict | None = None

    def to_source_file(self) -> SourceFile:
        return SourceFile(
            source_name=self.source_name,
            relative_path=self.source_path,
            file_name=self.file_name,
            file_type=self.file_type,
            size_bytes=self.size_bytes,
            modified_at=datetime.fromisoformat(self.modified_at),
            content_hash=self.content_hash,
            absolute_path=self.absolute_path,
        )

    def to_dict(self) -> dict:
        """JSON-safe form (vectors are staged separately as .npy files)."""
        return {
            "document_id": self.document_id,
            "tenant_id": self.tenant_id,
            "version": self.version,
            "action": self.action,
            "source_name": self.source_name,
            "source_path": self.source_path,
            "file_name": self.file_name,
            "file_type": self.file_type,
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at,
            "content_hash": self.content_hash,
            "absolute_path": self.absolute_path,
            "owner_id": self.owner_id,
            "allowed_groups": list(self.allowed_groups),
            "status": self.status,
            "object_key": self.object_key,
            "title": self.title,
            "page_count": self.page_count,
            "sections": [s.__dict__ for s in self.sections],
            "chunks": [c.to_payload() for c in self.chunks],
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkItem":
        data = dict(data)
        data["sections"] = [ParsedSection(**s) for s in data.get("sections", [])]
        data["chunks"] = [Chunk(**c) for c in data.get("chunks", [])]
        return cls(**data)
