# Retrieval design

## Candidate generation

- **BM25** (OpenSearch): `multi_match` over `section_title^2`, `text` (English analyzer, stemmed)
  and `text.exact^1.5` (standard analyzer, keeps identifiers like `ERR-4021` intact). Terms in
  double quotes become mandatory `match_phrase` clauses.
- **Dense** (Qdrant): cosine similarity over embeddings of `section title + chunk text`.

Both searches receive the user's access filter and an optional document version, and both fetch
`CANDIDATE_POOL` (default 30) candidates. In hybrid mode they run in parallel.

## Reciprocal Rank Fusion

```
score(d) = sum over retrievers r of  weight_r / (k + rank_r(d))
```

Ranks start at 1; `k` defaults to 60 (`RRF_K`); weights default to 1.0 (`RRF_WEIGHT_BM25`,
`RRF_WEIGHT_VECTOR`). Only ranks are used, so BM25 scores and cosine similarities need no
normalization. A chunk found by both retrievers gets two contributions and tends to rise. A larger
`k` makes the fusion treat ranks more evenly; a smaller `k` rewards the very top ranks. Ties are
broken by best individual rank, then chunk id, which keeps results deterministic. Every hit carries
`bm25_rank`, `vector_rank` and `rrf_score` signals so the ranking can be explained.

## Reranking

Optional. A cross-encoder (`RERANKER_MODEL`, default `cross-encoder/ms-marco-MiniLM-L-6-v2`)
scores `(query, chunk)` pairs for the first `RERANK_CANDIDATES` fused results and reorders them.
It is off by default in the API (`rerank: false`). Whether it helps on this corpus is a question
for `contextforge evaluate`; the report prints the measured difference and the project makes no
accuracy claim without it.

## Validation

After ranking, every hit is checked against PostgreSQL: the document must exist, not be deleted,
be visible to the user under its current ACL, and the chunk must belong to `indexed_version`. See
`access-control.md`.

## Latency breakdown

Each response includes `embed_ms`, `bm25_ms`, `vector_ms`, `fusion_ms`, `rerank_ms`, `validate_ms`
and `total_ms`. In hybrid mode `bm25_ms` and `vector_ms` overlap.

## Query handling

Queries are not rewritten or expanded. Quoted phrases are the only special syntax.
