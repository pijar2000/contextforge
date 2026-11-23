"""Low-level text splitting helpers shared by both chunking strategies."""


def window_spans(text: str, size: int, overlap: int) -> list[tuple[int, int]]:
    """Slide a window of `size` characters with `overlap`, cutting at natural boundaries.

    The cut prefers a paragraph break, then a sentence end, then a line break, then a space,
    searching only the last 20% of the window so chunks stay close to the requested size.
    """
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("chunk size must be positive and overlap must be in [0, size)")
    spans: list[tuple[int, int]] = []
    n = len(text)
    start = 0
    while start < n:
        end = min(start + size, n)
        if end < n:
            lo = start + int(size * 0.8)
            for sep, keep in (("\n\n", 0), (". ", 1), ("\n", 0), (" ", 0)):
                idx = text.rfind(sep, lo, end)
                if idx != -1 and idx + keep > start:
                    end = idx + keep
                    break
        if text[start:end].strip():
            spans.append((start, end))
        if end >= n:
            break
        nxt = max(end - overlap, start + 1)
        while nxt < end and not text[nxt - 1].isspace():  # begin on a word boundary
            nxt += 1
        start = nxt if nxt > start else end
    return spans


def split_by_paragraphs(text: str, max_chars: int, overlap: int) -> list[str]:
    """Pack whole paragraphs up to `max_chars`; oversized paragraphs fall back to windows."""
    pieces: list[str] = []
    current: list[str] = []
    length = 0
    for para in (p.strip() for p in text.split("\n\n")):
        if not para:
            continue
        if len(para) > max_chars:
            if current:
                pieces.append("\n\n".join(current))
                current, length = [], 0
            pieces.extend(para[a:b].strip() for a, b in window_spans(para, max_chars, overlap))
            continue
        added = len(para) + (2 if current else 0)
        if current and length + added > max_chars:
            pieces.append("\n\n".join(current))
            current, length = [], 0
            added = len(para)
        current.append(para)
        length += added
    if current:
        pieces.append("\n\n".join(current))
    return [p for p in pieces if p]
