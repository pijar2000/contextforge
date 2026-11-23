import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from contextforge.common.hashing import sha256_file
from contextforge.connectors.base import SourceConnector, SourceFile
from contextforge.parsing import EXTENSION_TO_TYPE

logger = logging.getLogger(__name__)


class FilesystemConnector(SourceConnector):
    def __init__(self, root: Path, source_name: str = "local-fs", subpath: Path | None = None):
        """`subpath` limits scanning to one sub-directory; relative paths stay root-relative so
        document ids and access rules do not depend on how the scan was started."""
        self.root = Path(root).resolve()
        self.source_name = source_name
        self.scan_root = Path(subpath).resolve() if subpath else self.root
        if not self.root.is_dir():
            raise FileNotFoundError(f"source directory does not exist: {self.root}")
        if self.scan_root != self.root and self.root not in self.scan_root.parents:
            raise ValueError("subpath must be inside the source root")

    @property
    def scope_prefix(self) -> str | None:
        """Only documents under this prefix may be treated as deleted after a scan."""
        if self.scan_root == self.root:
            return None
        return self.scan_root.relative_to(self.root).as_posix() + "/"

    def scan(self) -> Iterator[SourceFile]:
        for path in sorted(self.scan_root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            if any(part.startswith(".") for part in path.relative_to(self.scan_root).parts):
                continue  # hidden files and directories
            file_type = EXTENSION_TO_TYPE.get(path.suffix.lower())
            if file_type is None:
                continue
            try:
                stat = path.stat()
                digest = sha256_file(path)
            except OSError as exc:
                # Unreadable files are reported rather than silently dropped.
                logger.warning("cannot read %s: %s", path, exc)
                continue
            yield SourceFile(
                source_name=self.source_name,
                relative_path=path.relative_to(self.root).as_posix(),
                file_name=path.name,
                file_type=file_type,
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                content_hash=digest,
                absolute_path=str(path),
            )

    def read(self, file: SourceFile) -> bytes:
        return Path(file.absolute_path).read_bytes()
