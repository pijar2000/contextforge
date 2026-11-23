from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SourceFile:
    source_name: str
    relative_path: str  # posix-style, unique within the source
    file_name: str
    file_type: str
    size_bytes: int
    modified_at: datetime
    content_hash: str
    absolute_path: str


class SourceConnector(ABC):
    """Interface for document sources.

    A new source (S3, SharePoint, ...) needs `scan` to enumerate files with a content hash and
    `read` to fetch bytes. Everything downstream works from those two operations.
    """

    source_name: str

    @abstractmethod
    def scan(self) -> Iterator[SourceFile]: ...

    @abstractmethod
    def read(self, file: SourceFile) -> bytes: ...
