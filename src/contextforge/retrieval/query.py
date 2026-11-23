import re
from dataclasses import dataclass

_PHRASE = re.compile(r'"([^"]+)"')
_TOKEN = re.compile(r"\w+")


@dataclass(frozen=True)
class ParsedQuery:
    raw: str
    free_text: str
    phrases: tuple[str, ...]


def parse_query(raw: str) -> ParsedQuery:
    """Double-quoted segments are treated as exact phrases; the rest is free text."""
    phrases = tuple(p.strip() for p in _PHRASE.findall(raw) if p.strip())
    free = _PHRASE.sub(" ", raw)
    return ParsedQuery(raw=raw, free_text=" ".join(free.split()), phrases=phrases)


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())
