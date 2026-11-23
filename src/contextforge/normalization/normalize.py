"""Text clean-up applied between parsing and chunking."""

import re
import unicodedata
from collections import defaultdict

from contextforge.common.models import ParsedDocument, ParsedSection

_PAGE_NUMBER_LINE = re.compile(
    r"^\s*(page\s+\d+(\s+(of|/)\s+\d+)?|\d+\s*(/|of)\s*\d+|-\s*\d+\s*-|\d{1,4})\s*$", re.I
)
_HYPHEN_BREAK = re.compile(r"(\w)-\n([a-z])")
_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff\u00ad"), None)


def normalize_text(text: str, reflow: bool = False) -> str:
    """Unicode-normalize and tidy whitespace.

    `reflow` joins hard line wraps inside paragraphs; it is meant for PDF text, where lines are
    wrapped by layout rather than by the author.
    """
    text = unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    text = _HYPHEN_BREAK.sub(r"\1\2", text)  # "infra-\nstructure" -> "infrastructure"
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    if reflow:
        paragraphs = re.split(r"\n{2,}", text)
        text = "\n\n".join(" ".join(p.split("\n")) for p in paragraphs)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _strip_page_furniture(sections: list[ParsedSection], page_count: int | None) -> None:
    """Drop page-number lines and headers/footers that repeat on most pages of a PDF."""
    for s in sections:
        s.text = "\n".join(ln for ln in s.text.split("\n") if not _PAGE_NUMBER_LINE.match(ln))

    if not page_count or page_count < 3:
        return
    pages_with_line: dict[str, set[int]] = defaultdict(set)
    for s in sections:
        for ln in {ln.strip() for ln in s.text.split("\n") if ln.strip()}:
            if s.page_number is not None and len(ln) <= 100:
                pages_with_line[ln].add(s.page_number)
    repeated = {ln for ln, pages in pages_with_line.items() if len(pages) / page_count >= 0.6}
    if repeated:
        for s in sections:
            s.text = "\n".join(ln for ln in s.text.split("\n") if ln.strip() not in repeated)


def normalize_document(doc: ParsedDocument, file_type: str) -> ParsedDocument:
    reflow = file_type == "pdf"
    sections = [
        ParsedSection(
            title=normalize_text(s.title) if s.title else None,
            level=s.level,
            text=s.text,
            page_number=s.page_number,
        )
        for s in doc.sections
    ]
    if file_type == "pdf":
        _strip_page_furniture(sections, doc.page_count)
    for s in sections:
        s.text = normalize_text(s.text, reflow=reflow)
    sections = [s for s in sections if s.text]
    return ParsedDocument(
        title=normalize_text(doc.title) if doc.title else None,
        sections=sections,
        page_count=doc.page_count,
        metadata=doc.metadata,
    )
