"""In-memory index implementations.

They follow the same contracts as the Qdrant and OpenSearch adapters, including access
filtering inside the index, so unit tests and the `local` backend exercise the real pipeline
logic without containers. They are not tuned for large corpora.
"""

import math
import threading
from collections import Counter

import numpy as np

from contextforge.access_control.models import AccessFilter, payload_allows
from contextforge.common.models import Chunk, Hit
from contextforge.indexing.base import KeywordIndex, VectorIndex
from contextforge.retrieval.query import parse_query, tokenize


def _matches(payload: dict, document_id, version, keep_version) -> bool:
    if document_id is not None and payload["document_id"] != document_id:
        return False
    if version is not None and payload["document_version"] != version:
        return False
    if keep_version is not None and payload["document_version"] == keep_version:
        return False
    return True


class InMemoryVectorIndex(VectorIndex):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, tuple[dict, np.ndarray]] = {}

    def ensure(self) -> None:
        pass

    def upsert(self, chunks: list[Chunk], vectors: np.ndarray) -> None:
        with self._lock:
            for chunk, vec in zip(chunks, vectors, strict=True):
                self._items[chunk.chunk_id] = (chunk.to_payload(), np.asarray(vec, dtype=np.float32))

    def delete_document(self, document_id: str, keep_version: int | None = None) -> None:
        with self._lock:
            for cid in [
                c
                for c, (p, _) in self._items.items()
                if _matches(p, document_id, None, keep_version)
            ]:
                del self._items[cid]

    def search(self, vector, top_k, access: AccessFilter, document_version=None) -> list[Hit]:
        query = np.asarray(vector, dtype=np.float32)
        scored = []
        with self._lock:
            for payload, vec in self._items.values():
                if not payload_allows(payload, access):
                    continue
                if document_version is not None and payload["document_version"] != document_version:
                    continue
                denom = float(np.linalg.norm(query) * np.linalg.norm(vec)) or 1.0
                scored.append((float(np.dot(query, vec)) / denom, payload))
        scored.sort(key=lambda pair: (-pair[0], pair[1]["chunk_id"]))
        return [Hit.from_payload(p, s, "vector") for s, p in scored[:top_k] if s > 0]

    def count(self, document_id=None, version=None) -> int:
        with self._lock:
            return sum(1 for p, _ in self._items.values() if _matches(p, document_id, version, None))

    def ping(self) -> bool:
        return True


class InMemoryKeywordIndex(KeywordIndex):
    """BM25 (k1=1.2, b=0.75) over chunk text, with section titles counted double."""

    K1 = 1.2
    B = 0.75

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, tuple[dict, Counter, int, str]] = {}
        self._df: Counter = Counter()
        self._total_len = 0

    def ensure(self) -> None:
        pass

    def _remove(self, chunk_id: str) -> None:
        _, tf, length, _ = self._items.pop(chunk_id)
        self._df.subtract(tf.keys())
        self._total_len -= length

    def upsert(self, chunks: list[Chunk]) -> None:
        with self._lock:
            for chunk in chunks:
                if chunk.chunk_id in self._items:
                    self._remove(chunk.chunk_id)
                body = tokenize(chunk.text)
                title = tokenize(chunk.section_title or "")
                tf = Counter(body)
                for tok in title:
                    tf[tok] += 2
                length = len(body) + 2 * len(title)
                self._items[chunk.chunk_id] = (chunk.to_payload(), tf, length, chunk.text.lower())
                self._df.update(tf.keys())
                self._total_len += length

    def delete_document(self, document_id: str, keep_version: int | None = None) -> None:
        with self._lock:
            for cid in [
                c
                for c, (p, *_rest) in self._items.items()
                if _matches(p, document_id, None, keep_version)
            ]:
                self._remove(cid)

    def search(self, query, top_k, access: AccessFilter, document_version=None) -> list[Hit]:
        parsed = parse_query(query)
        terms = tokenize(parsed.free_text) + [t for ph in parsed.phrases for t in tokenize(ph)]
        if not terms:
            return []
        with self._lock:
            n_docs = len(self._items)
            if n_docs == 0:
                return []
            avg_len = self._total_len / n_docs or 1.0
            scored = []
            for payload, tf, length, lowered in self._items.values():
                if not payload_allows(payload, access):
                    continue
                if document_version is not None and payload["document_version"] != document_version:
                    continue
                if any(" ".join(tokenize(ph)) not in " ".join(tokenize(lowered)) for ph in parsed.phrases):
                    continue  # quoted phrases are mandatory
                score = 0.0
                for term in set(terms):
                    freq = tf.get(term, 0)
                    if not freq:
                        continue
                    df = self._df[term]
                    idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
                    norm = freq + self.K1 * (1 - self.B + self.B * length / avg_len)
                    score += idf * freq * (self.K1 + 1) / norm
                if score > 0:
                    scored.append((score, payload))
        scored.sort(key=lambda pair: (-pair[0], pair[1]["chunk_id"]))
        return [Hit.from_payload(p, s, "bm25") for s, p in scored[:top_k]]

    def count(self, document_id=None, version=None) -> int:
        with self._lock:
            return sum(
                1 for p, *_ in self._items.values() if _matches(p, document_id, version, None)
            )

    def ping(self) -> bool:
        return True
