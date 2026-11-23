"""Format-specific text extraction. Every parser takes raw bytes so the same code path serves
first-time ingestion and re-indexing from the object store."""

import io
import re
from collections import Counter

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt

from contextforge.common.models import ParsedDocument, ParsedSection
from contextforge.parsing.errors import ParsingError

EXTENSION_TO_TYPE = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".txt": "txt",
    ".md": "markdown",
    ".markdown": "markdown",
    ".html": "html",
    ".htm": "html",
}


def decode_text(data: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1"), "latin-1"


# ---------------------------------------------------------------- PDF
def parse_pdf(data: bytes) -> ParsedDocument:
    import fitz  # PyMuPDF; imported lazily so other formats work without it

    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ParsingError("pdf", "file could not be opened as a PDF", repr(exc)) from exc
    if doc.needs_pass:
        raise ParsingError("pdf", "PDF is password protected")

    pages: list[list[tuple[str, float]]] = []
    size_weight: Counter = Counter()
    try:
        for page in doc:
            lines: list[tuple[str, float]] = []
            for block in page.get_text("dict").get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    spans = [s for s in line.get("spans", []) if s["text"].strip()]
                    if not spans:
                        continue
                    text = "".join(s["text"] for s in line["spans"]).strip()
                    size = round(max(s["size"] for s in spans), 1)
                    size_weight[size] += len(text)
                    lines.append((text, size))
                lines.append(("", 0.0))  # block boundary becomes a paragraph break
            pages.append(lines)
        page_count = doc.page_count
        meta_title = (doc.metadata or {}).get("title") or None
    except Exception as exc:
        raise ParsingError("pdf", "text extraction failed", repr(exc)) from exc
    finally:
        doc.close()

    body_size = size_weight.most_common(1)[0][0] if size_weight else 0.0
    sections: list[ParsedSection] = []
    current_title: str | None = None
    current_level = 1
    first_heading: str | None = None

    for page_number, lines in enumerate(pages, start=1):
        buffer: list[str] = []

        def flush(buf=buffer, pn=page_number):
            text = "\n".join(buf).strip()
            if text:
                sections.append(ParsedSection(current_title, current_level, text, pn))
            buf.clear()

        for text, size in lines:
            is_heading = bool(text) and body_size and size >= body_size * 1.15 and len(text) <= 120
            if is_heading:
                flush()
                current_title = text
                current_level = 1 if size >= body_size * 1.5 else 2
                first_heading = first_heading or text
            else:
                buffer.append(text)
        flush()

    return ParsedDocument(
        title=meta_title or first_heading,
        sections=sections,
        page_count=page_count,
        metadata={"parser": "pymupdf"},
    )


# ---------------------------------------------------------------- DOCX
def parse_docx(data: bytes) -> ParsedDocument:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        doc = Document(io.BytesIO(data))
    except Exception as exc:
        raise ParsingError("docx", "file could not be opened as DOCX", repr(exc)) from exc

    sections: list[ParsedSection] = []
    title: str | None = None
    current_title: str | None = None
    level = 1
    buffer: list[str] = []

    def flush():
        text = "\n".join(buffer).strip()
        if text:
            sections.append(ParsedSection(current_title, level, text, None))
        buffer.clear()

    try:
        for child in doc.element.body.iterchildren():
            if child.tag.endswith("}p"):
                para = Paragraph(child, doc)
                text = para.text.strip()
                if not text:
                    buffer.append("")
                    continue
                style = (para.style.name if para.style is not None else "") or ""
                if style == "Title":
                    title = title or text
                elif style.startswith("Heading"):
                    flush()
                    current_title = text
                    digits = "".join(ch for ch in style if ch.isdigit())
                    level = int(digits) if digits else 1
                    title = title or text
                elif style.startswith("List"):
                    buffer.append(f"- {text}")
                else:
                    buffer.append(text)
            elif child.tag.endswith("}tbl"):
                table = Table(child, doc)
                for row in table.rows:
                    cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                    buffer.append(" | ".join(cells))
                buffer.append("")
        flush()
    except Exception as exc:
        raise ParsingError("docx", "content extraction failed", repr(exc)) from exc

    return ParsedDocument(title=title, sections=sections, metadata={"parser": "python-docx"})


# ---------------------------------------------------------------- HTML
_BLOCK_TAGS = ["p", "li", "pre", "blockquote", "tr", "dt", "dd"]
_HEADING_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6"]


def parse_html(data: bytes) -> ParsedDocument:
    text, encoding = decode_text(data)
    try:
        soup = BeautifulSoup(text, "html.parser")
    except Exception as exc:
        raise ParsingError("html", "HTML could not be parsed", repr(exc)) from exc

    for tag in soup(["script", "style", "noscript", "nav", "footer", "aside", "template"]):
        tag.decompose()

    doc_title = soup.title.get_text(strip=True) if soup.title else None
    root = soup.body or soup
    sections: list[ParsedSection] = []
    current_title: str | None = None
    level = 1
    buffer: list[str] = []

    def flush():
        body = "\n".join(buffer).strip()
        if body:
            sections.append(ParsedSection(current_title, level, body, None))
        buffer.clear()

    for el in root.find_all(_HEADING_TAGS + _BLOCK_TAGS):
        if el.name in _HEADING_TAGS:
            heading = el.get_text(" ", strip=True)
            if heading:
                flush()
                current_title = heading
                level = int(el.name[1])
                doc_title = doc_title or heading
            continue
        if el.find(_BLOCK_TAGS):  # container whose children are handled separately
            continue
        content = el.get_text(" ", strip=True)
        if not content:
            continue
        if el.name == "li":
            content = f"- {content}"
        elif el.name == "tr":
            content = " | ".join(c.get_text(" ", strip=True) for c in el.find_all(["th", "td"]))
        buffer.append(content)
        buffer.append("")
    flush()
    return ParsedDocument(title=doc_title, sections=sections, metadata={"encoding": encoding})


# ---------------------------------------------------------------- Markdown
def parse_markdown(data: bytes) -> ParsedDocument:
    text, encoding = decode_text(data)
    tokens = MarkdownIt("commonmark").enable("table").parse(text)

    sections: list[ParsedSection] = []
    current_title: str | None = None
    level = 1
    doc_title: str | None = None
    buffer: list[str] = []

    def flush():
        body = "\n".join(buffer).strip()
        if body:
            sections.append(ParsedSection(current_title, level, body, None))
        buffer.clear()

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.type == "heading_open":
            flush()
            inline = tokens[i + 1] if i + 1 < len(tokens) else None
            current_title = inline.content.strip() if inline is not None else None
            level = int(tok.tag[1])
            doc_title = doc_title or current_title
            i += 3
            continue
        if tok.type == "inline":
            buffer.append(tok.content)
        elif tok.type in ("fence", "code_block"):
            buffer.append(tok.content.rstrip())
        elif tok.type in ("paragraph_close", "tr_close"):
            buffer.append("")
        i += 1
    flush()
    return ParsedDocument(title=doc_title, sections=sections, metadata={"encoding": encoding})


# ---------------------------------------------------------------- plain text
_UNDERLINE = re.compile(r"^(=|-){3,}\s*$")


def _is_caps_heading(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return 3 <= len(letters) and line.strip().upper() == line.strip() and len(line.strip()) <= 80


def parse_text(data: bytes) -> ParsedDocument:
    text, encoding = decode_text(data)
    lines = text.splitlines()
    sections: list[ParsedSection] = []
    current_title: str | None = None
    doc_title: str | None = None
    buffer: list[str] = []

    def flush():
        body = "\n".join(buffer).strip()
        if body:
            sections.append(ParsedSection(current_title, 1, body, None))
        buffer.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        previous_blank = i == 0 or not lines[i - 1].strip()
        if line.strip() and _UNDERLINE.match(nxt):
            flush()
            current_title = line.strip()
            doc_title = doc_title or current_title
            i += 2
            continue
        if line.strip() and previous_blank and _is_caps_heading(line):
            flush()
            current_title = line.strip().title()
            doc_title = doc_title or current_title
            i += 1
            continue
        buffer.append(line)
        i += 1
    flush()
    return ParsedDocument(title=doc_title, sections=sections, metadata={"encoding": encoding})


PARSERS = {
    "pdf": parse_pdf,
    "docx": parse_docx,
    "html": parse_html,
    "markdown": parse_markdown,
    "txt": parse_text,
}


def parse_document(data: bytes, file_type: str) -> ParsedDocument:
    parser = PARSERS.get(file_type)
    if parser is None:
        raise ParsingError(file_type, f"unsupported file type: {file_type}")
    if not data:
        return ParsedDocument(title=None, sections=[], metadata={"note": "zero-byte file"})
    return parser(data)
