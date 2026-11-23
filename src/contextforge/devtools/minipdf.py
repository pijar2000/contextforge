"""Minimal PDF writer (Helvetica only) used to generate sample and test PDFs without extra
dependencies. It supports headings, wrapped paragraphs and a repeating header/footer."""

HEADING = {"h1": ("F2", 18, 26), "h2": ("F2", 14, 22), "p": ("F1", 11, 15)}
LEFT, RIGHT, TOP, BOTTOM = 50, 545, 780, 70


def _esc(text: str) -> bytes:
    raw = text.encode("cp1252", "replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _wrap(text: str, size: int) -> list[str]:
    max_chars = int((RIGHT - LEFT) / (size * 0.5))
    lines, current = [], ""
    for word in text.split():
        if current and len(current) + 1 + len(word) > max_chars:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    return lines + ([current] if current else [])


def _page_stream(blocks, header: str, footer: str) -> bytes:
    ops: list[bytes] = []

    def text(font, size, x, y, value):
        ops.append(b"BT /%s %d Tf %d %d Td (" % (font.encode(), size, x, y) + _esc(value) + b") Tj ET")

    y = TOP
    for kind, value in blocks:
        font, size, leading = HEADING[kind]
        if kind != "p":
            y -= 8
        for line in _wrap(value, size):
            text(font, size, LEFT, y, line)
            y -= leading
        y -= 8  # gap between blocks keeps them separate text blocks for the extractor
        if y < BOTTOM:
            raise ValueError("page overflow: split the content across more pages")
    text("F1", 9, LEFT, 815, header)
    text("F1", 9, LEFT, 40, footer)
    return b"\n".join(ops)


def build_pdf(pages: list[list[tuple[str, str]]], header: str = "") -> bytes:
    """`pages` is a list of pages; each page is a list of (kind, text), kind in h1|h2|p."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog, tree = add(b""), add(b"")
    f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    f2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    page_ids = []
    for number, blocks in enumerate(pages, start=1):
        stream = _page_stream(blocks, header, f"Page {number} of {len(pages)}")
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page_ids.append(
            add(
                (
                    f"<< /Type /Page /Parent {tree} 0 R /MediaBox [0 0 595 842] "
                    f"/Resources << /Font << /F1 {f1} 0 R /F2 {f2} 0 R >> >> /Contents {content} 0 R >>"
                ).encode()
            )
        )
    objects[catalog - 1] = f"<< /Type /Catalog /Pages {tree} 0 R >>".encode()
    kids = " ".join(f"{i} 0 R" for i in page_ids)
    objects[tree - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)
