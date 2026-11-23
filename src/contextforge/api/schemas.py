from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    source_path: str | None = Field(
        default=None, description="Sub-directory of SOURCE_ROOT to ingest; defaults to the whole root."
    )
    force: bool = Field(default=False, description="Re-index every document even if unchanged.")


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    mode: Literal["bm25", "vector", "hybrid"] = "hybrid"
    top_k: int = Field(default=5, ge=1, le=50)
    rerank: bool = False
    document_version: int | None = Field(default=None, ge=1)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    mode: Literal["bm25", "vector", "hybrid"] = "hybrid"
    top_k: int = Field(default=5, ge=1, le=20)
    rerank: bool = False


class HitOut(BaseModel):
    chunk_id: str
    document_id: str
    document_version: int
    chunk_index: int
    source_path: str
    section_title: str | None
    page_number: int | None
    score: float
    text: str
    signals: dict


class SearchResponseOut(BaseModel):
    query: str
    mode: str
    rerank: bool
    hits: list[HitOut]
    timings_ms: dict[str, float]
    counts: dict[str, int]


class DocumentOut(BaseModel):
    document_id: str
    source_path: str
    file_name: str
    file_type: str
    title: str | None
    status: str
    current_version: int
    indexed_version: int | None
    size_bytes: int
    content_hash: str
    owner_id: str
    allowed_groups: list[str]
    last_ingested_at: datetime | None
    last_error: str | None = None


class VersionOut(BaseModel):
    version: int
    status: str
    content_hash: str
    chunk_count: int
    page_count: int | None
    indexed_at: datetime | None
    error: str | None = None


class DocumentDetail(DocumentOut):
    versions: list[VersionOut]


class DocumentPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[DocumentOut]
