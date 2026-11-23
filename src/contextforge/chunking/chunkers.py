"""Two chunking strategies that produce identical metadata.

fixed      Slides a window over the whole document text. Simple and predictable, but may cut
           across headings.
structure  Keeps section boundaries. Small neighbouring sections are merged, large sections are
           split on paragraphs. A chunk never spans a page break when the format is paged, so
           page citations stay exact.
"""

from dataclasses import dataclass

from contextforge.chunking.splitting import split_by_paragraphs, window_spans
from contextforge.common.hashing import chunk_id_for
from contextforge.common.models import Chunk, ParsedDocument


@dataclass(frozen=True)
class DocumentContext:
    document_id: str
    version: int
    source_path: str
    tenant_id: str
    owner_id: str
    allowed_groups: tuple[str, ...]


@dataclass(frozen=True)
class ChunkingConfig:
    strategy: str = "structure"
    size: int = 1000
    overlap: int = 150
    min_size: int = 200


def _make(ctx: DocumentContext, index: int, text: str, title, page) -> Chunk:
    return Chunk(
        chunk_id=chunk_id_for(ctx.document_id, ctx.version, index),
        document_id=ctx.document_id,
        document_version=ctx.version,
        chunk_index=index,
        text=text,
        section_title=title,
        page_number=page,
        source_path=ctx.source_path,
        tenant_id=ctx.tenant_id,
        owner_id=ctx.owner_id,
        allowed_groups=list(ctx.allowed_groups),
    )


def fixed_size_chunks(doc: ParsedDocument, ctx: DocumentContext, cfg: ChunkingConfig) -> list[Chunk]:
    parts: list[str] = []
    marks: list[tuple[int, str | None, int | None]] = []  # (start offset, title, page)
    offset = 0
    for section in doc.sections:
        marks.append((offset, section.title, section.page_number))
        parts.append(section.text)
        offset += len(section.text) + 2
    full = "\n\n".join(parts)

    chunks: list[Chunk] = []
    for start, end in window_spans(full, cfg.size, cfg.overlap):
        title, page = None, None
        for mark_start, mark_title, mark_page in marks:
            if mark_start <= start:
                title, page = mark_title, mark_page
            else:
                break
        chunks.append(_make(ctx, len(chunks), full[start:end].strip(), title, page))
    return chunks


def structure_aware_chunks(
    doc: ParsedDocument, ctx: DocumentContext, cfg: ChunkingConfig
) -> list[Chunk]:
    chunks: list[Chunk] = []
    pending_title: str | None = None
    pending_page: int | None = None
    pending_text = ""

    def emit(title, page, text):
        for piece in split_by_paragraphs(text, cfg.size, cfg.overlap):
            chunks.append(_make(ctx, len(chunks), piece, title, page))

    for section in doc.sections:
        if pending_text:
            same_page = pending_page == section.page_number
            if same_page and len(pending_text) < cfg.min_size:
                # Fold a tiny section into the next one, keeping its heading as text.
                head = f"{section.title}\n" if section.title and section.title != pending_title else ""
                pending_text = f"{pending_text}\n\n{head}{section.text}"
                continue
            emit(pending_title, pending_page, pending_text)
        pending_title, pending_page, pending_text = section.title, section.page_number, section.text
    if pending_text:
        emit(pending_title, pending_page, pending_text)
    return chunks


def chunk_document(doc: ParsedDocument, ctx: DocumentContext, cfg: ChunkingConfig) -> list[Chunk]:
    if cfg.strategy == "fixed":
        return fixed_size_chunks(doc, ctx, cfg)
    if cfg.strategy == "structure":
        return structure_aware_chunks(doc, ctx, cfg)
    raise ValueError(f"unknown chunk strategy: {cfg.strategy!r} (use 'fixed' or 'structure')")
