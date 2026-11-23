"""Plain data structures shared across pipeline stages."""

from dataclasses import asdict, dataclass, field


@dataclass
class ParsedSection:
    """A contiguous piece of text under one heading, located on one page (if paged)."""

    title: str | None
    level: int
    text: str
    page_number: int | None = None


@dataclass
class ParsedDocument:
    title: str | None
    sections: list[ParsedSection]
    page_count: int | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not any(s.text.strip() for s in self.sections)


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    document_version: int
    chunk_index: int
    text: str
    section_title: str | None
    page_number: int | None
    source_path: str
    tenant_id: str
    owner_id: str
    allowed_groups: list[str]

    @property
    def embedding_text(self) -> str:
        """Section titles carry meaning that the body often omits, so embed them together."""
        return f"{self.section_title}\n{self.text}" if self.section_title else self.text

    def to_payload(self) -> dict:
        return asdict(self)


@dataclass
class Hit:
    chunk_id: str
    document_id: str
    document_version: int
    chunk_index: int
    text: str
    section_title: str | None
    page_number: int | None
    source_path: str
    tenant_id: str
    score: float = 0.0
    signals: dict = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict, score: float, signal: str | None = None) -> "Hit":
        return cls(
            chunk_id=payload["chunk_id"],
            document_id=payload["document_id"],
            document_version=int(payload["document_version"]),
            chunk_index=int(payload["chunk_index"]),
            text=payload["text"],
            section_title=payload.get("section_title"),
            page_number=payload.get("page_number"),
            source_path=payload["source_path"],
            tenant_id=payload["tenant_id"],
            score=float(score),
            signals={signal: float(score)} if signal else {},
        )

    def citation(self) -> dict:
        return {
            "document_id": self.document_id,
            "source_path": self.source_path,
            "version": self.document_version,
            "section_title": self.section_title,
            "page_number": self.page_number,
            "chunk_id": self.chunk_id,
        }
