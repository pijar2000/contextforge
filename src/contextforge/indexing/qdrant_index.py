import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from contextforge.access_control.models import AccessFilter
from contextforge.common.hashing import point_id_for
from contextforge.common.models import Chunk, Hit
from contextforge.indexing.base import VectorIndex


class QdrantVectorIndex(VectorIndex):
    def __init__(self, url: str, collection: str, dim: int, client: QdrantClient | None = None):
        self.collection = collection
        self.dim = dim
        self.client = client or QdrantClient(url=url, timeout=30)

    def ensure(self) -> None:
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=qm.VectorParams(size=self.dim, distance=qm.Distance.COSINE),
            )
        for field in ("tenant_id", "document_id", "owner_id", "allowed_groups"):
            self.client.create_payload_index(
                self.collection, field_name=field, field_schema=qm.PayloadSchemaType.KEYWORD
            )
        self.client.create_payload_index(
            self.collection, field_name="document_version", field_schema=qm.PayloadSchemaType.INTEGER
        )

    def upsert(self, chunks: list[Chunk], vectors: np.ndarray) -> None:
        # Point ids are derived from chunk ids, so re-running an upsert overwrites, never duplicates.
        points = [
            qm.PointStruct(id=point_id_for(c.chunk_id), vector=v.tolist(), payload=c.to_payload())
            for c, v in zip(chunks, vectors, strict=True)
        ]
        for i in range(0, len(points), 128):
            self.client.upsert(self.collection, points=points[i : i + 128], wait=True)

    def delete_document(self, document_id: str, keep_version: int | None = None) -> None:
        must = [qm.FieldCondition(key="document_id", match=qm.MatchValue(value=document_id))]
        must_not = []
        if keep_version is not None:
            must_not.append(
                qm.FieldCondition(key="document_version", match=qm.MatchValue(value=keep_version))
            )
        self.client.delete(
            self.collection,
            points_selector=qm.FilterSelector(filter=qm.Filter(must=must, must_not=must_not or None)),
            wait=True,
        )

    @staticmethod
    def _filter(access: AccessFilter, document_version: int | None) -> qm.Filter:
        must: list = [qm.FieldCondition(key="tenant_id", match=qm.MatchValue(value=access.tenant_id))]
        if not access.unrestricted_in_tenant:
            must.append(
                qm.Filter(
                    should=[
                        qm.FieldCondition(
                            key="allowed_groups", match=qm.MatchAny(any=list(access.groups) or [""])
                        ),
                        qm.FieldCondition(
                            key="owner_id", match=qm.MatchValue(value=access.user_id)
                        ),
                    ]
                )
            )
        if document_version is not None:
            must.append(
                qm.FieldCondition(key="document_version", match=qm.MatchValue(value=document_version))
            )
        return qm.Filter(must=must)

    def search(self, vector, top_k, access, document_version=None) -> list[Hit]:
        result = self.client.query_points(
            self.collection,
            query=np.asarray(vector, dtype=np.float32).tolist(),
            limit=top_k,
            query_filter=self._filter(access, document_version),
            with_payload=True,
        )
        return [Hit.from_payload(p.payload, p.score, "vector") for p in result.points]

    def count(self, document_id=None, version=None) -> int:
        must = []
        if document_id is not None:
            must.append(qm.FieldCondition(key="document_id", match=qm.MatchValue(value=document_id)))
        if version is not None:
            must.append(qm.FieldCondition(key="document_version", match=qm.MatchValue(value=version)))
        flt = qm.Filter(must=must) if must else None
        return self.client.count(self.collection, count_filter=flt, exact=True).count

    def ping(self) -> bool:
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False
