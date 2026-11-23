import re
from abc import ABC, abstractmethod
from io import BytesIO
from pathlib import Path


class ObjectStore(ABC):
    @abstractmethod
    def ensure(self) -> None: ...

    @abstractmethod
    def put(self, key: str, data: bytes) -> None: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def ping(self) -> bool: ...


def object_key(tenant_id: str, document_id: str, version: int, file_name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", file_name)
    return f"{tenant_id}/{document_id}/v{version}/{safe}"


class LocalObjectStore(ObjectStore):
    def __init__(self, root: Path):
        self.root = Path(root)

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("object key escapes the store root")
        return path

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def ping(self) -> bool:
        return self.root.exists()


class MinioObjectStore(ObjectStore):
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str, secure: bool):
        from minio import Minio

        self.bucket = bucket
        self.client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)

    def ensure(self) -> None:
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def put(self, key: str, data: bytes) -> None:
        self.client.put_object(self.bucket, key, BytesIO(data), length=len(data))

    def get(self, key: str) -> bytes:
        response = self.client.get_object(self.bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def ping(self) -> bool:
        try:
            return bool(self.client.bucket_exists(self.bucket))
        except Exception:
            return False
