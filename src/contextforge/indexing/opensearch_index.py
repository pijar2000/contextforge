from opensearchpy import OpenSearch, helpers

from contextforge.access_control.models import AccessFilter
from contextforge.common.models import Chunk, Hit
from contextforge.indexing.base import KeywordIndex
from contextforge.retrieval.query import parse_query

MAPPING = {
    "settings": {"index": {"number_of_shards": 1, "number_of_replicas": 0}},
    "mappings": {
        "properties": {
            "chunk_id": {"type": "keyword"},
            "document_id": {"type": "keyword"},
            "tenant_id": {"type": "keyword"},
            "owner_id": {"type": "keyword"},
            "allowed_groups": {"type": "keyword"},
            "document_version": {"type": "integer"},
            "chunk_index": {"type": "integer"},
            "page_number": {"type": "integer"},
            "source_path": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
            "section_title": {"type": "text", "analyzer": "english"},
            # `text` is stemmed for recall; `text.exact` keeps surface forms for phrases and codes.
            "text": {
                "type": "text",
                "analyzer": "english",
                "fields": {"exact": {"type": "text", "analyzer": "standard"}},
            },
        }
    },
}


class OpenSearchKeywordIndex(KeywordIndex):
    def __init__(self, url: str, index: str, client: OpenSearch | None = None):
        self.index = index
        self.client = client or OpenSearch(hosts=[url], use_ssl=False, verify_certs=False, timeout=30)

    def ensure(self) -> None:
        if not self.client.indices.exists(index=self.index):
            self.client.indices.create(index=self.index, body=MAPPING)

    def upsert(self, chunks: list[Chunk]) -> None:
        # Using chunk_id as _id makes repeated indexing overwrite instead of duplicate.
        actions = [
            {"_op_type": "index", "_index": self.index, "_id": c.chunk_id, "_source": c.to_payload()}
            for c in chunks
        ]
        helpers.bulk(self.client, actions, refresh="wait_for", raise_on_error=True)

    def delete_document(self, document_id: str, keep_version: int | None = None) -> None:
        bool_query: dict = {"filter": [{"term": {"document_id": document_id}}]}
        if keep_version is not None:
            bool_query["must_not"] = [{"term": {"document_version": keep_version}}]
        self.client.delete_by_query(
            index=self.index, body={"query": {"bool": bool_query}}, conflicts="proceed", refresh=True
        )

    @staticmethod
    def build_query(query: str, access: AccessFilter, document_version: int | None) -> dict:
        parsed = parse_query(query)
        filters: list[dict] = [{"term": {"tenant_id": access.tenant_id}}]
        if not access.unrestricted_in_tenant:
            filters.append(
                {
                    "bool": {
                        "should": [
                            {"terms": {"allowed_groups": list(access.groups) or [""]}},
                            {"term": {"owner_id": access.user_id}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )
        if document_version is not None:
            filters.append({"term": {"document_version": document_version}})

        must: list[dict] = []
        if parsed.free_text:
            must.append(
                {
                    "multi_match": {
                        "query": parsed.free_text,
                        "fields": ["section_title^2", "text", "text.exact^1.5"],
                        "type": "best_fields",
                    }
                }
            )
        for phrase in parsed.phrases:
            must.append({"match_phrase": {"text.exact": phrase}})
        if not must:
            must.append({"match_none": {}})
        return {"bool": {"must": must, "filter": filters}}

    def search(self, query, top_k, access, document_version=None) -> list[Hit]:
        body = {"size": top_k, "query": self.build_query(query, access, document_version)}
        response = self.client.search(index=self.index, body=body)
        return [
            Hit.from_payload(h["_source"], h["_score"], "bm25") for h in response["hits"]["hits"]
        ]

    def count(self, document_id=None, version=None) -> int:
        filters = []
        if document_id is not None:
            filters.append({"term": {"document_id": document_id}})
        if version is not None:
            filters.append({"term": {"document_version": version}})
        body = {"query": {"bool": {"filter": filters}}} if filters else None
        self.client.indices.refresh(index=self.index)
        return int(self.client.count(index=self.index, body=body)["count"])

    def ping(self) -> bool:
        try:
            return bool(self.client.ping())
        except Exception:
            return False
