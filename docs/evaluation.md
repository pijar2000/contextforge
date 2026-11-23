# Retrieval evaluation

## Dataset

`datasets/evaluation/queries.json` holds 28 fixed queries over the sample corpus. Each has an id,
a category (`exact_keyword`, `paraphrase`, `natural_question`), the expected source documents and
expected keywords. All documents and identities are fictional.

Relevant chunks are not hand-labelled. At evaluation time a chunk is relevant if it comes from an
expected source document **and** contains at least one expected keyword (case-insensitive). This
keeps judgments valid when chunking settings change, but see the limitations below.

## Metrics

| Metric | Definition |
|---|---|
| Recall@K | share of the expected source documents that appear in the top K results |
| Precision@K | relevant chunks in the top K, divided by K |
| Hit Rate@K | 1 if any relevant chunk is in the top K |
| MRR | 1 / rank of the first relevant chunk, 0 if none |
| Latency | wall-clock `total_ms` per query (fastest of `--repeats`); mean, p50, p95 |

K values: 1, 3, 5, 10. Queries run as the administrator `alice` so access control does not affect
the measurement.

## Strategies

`bm25`, `vector`, `hybrid` (RRF), `hybrid_rerank` (RRF then cross-encoder over the top
`RERANK_CANDIDATES`).

## Running

```bash
contextforge ingest && contextforge evaluate      # with Docker services running
contextforge evaluate --local                     # in-memory; indexes the sample corpus first
EMBEDDING_BACKEND=hashing contextforge evaluate --local   # offline, no model download
```

Output: `reports/evaluation/latest.json` and `latest.md` (also served by `GET /evaluation/results`
and shown in the dashboard). No results are committed to the repository; run the command to
produce them for your own configuration.

## Limitations

- 28 queries is small. A single query changes MRR by roughly 0.04, so small gaps between
  strategies are noise.
- Keyword-derived relevance favours lexical methods and cannot reward a chunk that answers the
  question with different words. Paraphrase queries are therefore harder to score fairly for dense
  retrieval.
- The corpus is 16 short documents. Dense and hybrid results on a corpus this small say little
  about behaviour at thousands of documents.
- The hashing embedder has no semantic understanding. Results with `EMBEDDING_BACKEND=hashing`
  must not be used to judge vector search or reranking.
- Latency is measured on one machine, single user, warm caches (the first query loads models).
- The reranker's effect is reported as a difference to `hybrid`; it may be positive, zero or
  negative on this data.
- No LLM answer evaluation is implemented. Assistant output is not scored.
