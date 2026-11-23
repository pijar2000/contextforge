"""Embedding backends behind one small interface."""

import hashlib
import re
from abc import ABC, abstractmethod

import numpy as np


class Embedder(ABC):
    name: str
    dim: int

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> np.ndarray: ...

    @abstractmethod
    def embed_query(self, text: str) -> np.ndarray: ...


class SentenceTransformerEmbedder(Embedder):
    def __init__(self, model_name: str, dim: int, query_prefix: str = "", batch_size: int = 32):
        self.name = model_name
        self.dim = dim
        self._prefix = query_prefix
        self._batch = batch_size
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.name)
            actual = self._model.get_sentence_embedding_dimension()
            if actual != self.dim:
                raise ValueError(
                    f"EMBEDDING_DIM={self.dim} but model {self.name} produces {actual} dimensions"
                )
        return self._model

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        vectors = self._load().encode(
            texts, batch_size=self._batch, normalize_embeddings=True, show_progress_bar=False
        )
        return np.asarray(vectors, dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([self._prefix + text])[0]


_TOKEN = re.compile(r"\w+")


class HashingEmbedder(Embedder):
    """Deterministic bag-of-words feature hashing.

    It has no semantic understanding (synonyms are unrelated), so it exists only for offline
    tests and smoke runs. Do not use it to judge vector-search quality.
    """

    def __init__(self, dim: int = 384):
        self.name = f"hashing-{dim}"
        self.dim = dim

    def _vector(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        for token in _TOKEN.findall(text.lower()):
            digest = hashlib.md5(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "little") % self.dim
            vec[idx] += 1.0 if digest[4] & 1 else -1.0
        norm = np.linalg.norm(vec)
        return vec / norm if norm else vec

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.stack([self._vector(t) for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._vector(text)


def build_embedder(settings) -> Embedder:
    if settings.embedding_backend == "hashing":
        return HashingEmbedder(settings.embedding_dim)
    if settings.embedding_backend == "sentence-transformers":
        return SentenceTransformerEmbedder(
            settings.embedding_model,
            settings.embedding_dim,
            settings.embedding_query_prefix,
            settings.embedding_batch_size,
        )
    raise ValueError(f"unknown EMBEDDING_BACKEND: {settings.embedding_backend!r}")
