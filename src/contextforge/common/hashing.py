import hashlib
import uuid
from pathlib import Path

_NAMESPACE = uuid.UUID("6f1c1b0e-6d7c-4a53-9a43-0a5c1f6b7a10")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def document_id_for(tenant_id: str, source_name: str, relative_path: str) -> str:
    """Stable identity: the same file path in the same source always maps to the same id.

    Content changes produce a new *version*, never a new document id.
    """
    return str(uuid.uuid5(_NAMESPACE, f"{tenant_id}|{source_name}|{relative_path}"))


def chunk_id_for(document_id: str, version: int, chunk_index: int) -> str:
    return f"{document_id}:v{version}:{chunk_index:05d}"


def point_id_for(chunk_id: str) -> str:
    """Qdrant requires UUID or integer ids; derive a deterministic UUID from the chunk id."""
    return str(uuid.uuid5(_NAMESPACE, chunk_id))
