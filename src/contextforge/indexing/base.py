from abc import ABC, abstractmethod

import numpy as np

from contextforge.access_control.models import AccessFilter
from contextforge.common.models import Chunk, Hit


class VectorIndex(ABC):
    @abstractmethod
    def ensure(self) -> None: ...

    @abstractmethod
    def upsert(self, chunks: list[Chunk], vectors: np.ndarray) -> None: ...

    @abstractmethod
    def delete_document(self, document_id: str, keep_version: int | None = None) -> None:
        """Remove a document's chunks; with `keep_version`, remove only other versions."""

    @abstractmethod
    def search(
        self,
        vector: np.ndarray,
        top_k: int,
        access: AccessFilter,
        document_version: int | None = None,
    ) -> list[Hit]: ...

    @abstractmethod
    def count(self, document_id: str | None = None, version: int | None = None) -> int: ...

    @abstractmethod
    def ping(self) -> bool: ...


class KeywordIndex(ABC):
    @abstractmethod
    def ensure(self) -> None: ...

    @abstractmethod
    def upsert(self, chunks: list[Chunk]) -> None: ...

    @abstractmethod
    def delete_document(self, document_id: str, keep_version: int | None = None) -> None: ...

    @abstractmethod
    def search(
        self,
        query: str,
        top_k: int,
        access: AccessFilter,
        document_version: int | None = None,
    ) -> list[Hit]: ...

    @abstractmethod
    def count(self, document_id: str | None = None, version: int | None = None) -> int: ...

    @abstractmethod
    def ping(self) -> bool: ...
