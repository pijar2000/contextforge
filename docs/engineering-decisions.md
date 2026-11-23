# Engineering decisions

**Stable document ids, versioned content.** The id is a UUIDv5 of tenant, source and path, so edits
produce versions rather than new documents and deletions can be detected by absence.

**Two version pointers.** `current_version` vs `indexed_version` lets the index be written in any
order while search stays consistent. The alternative (blue/green collections per run) uses more
storage and complicates single-document updates.

**PostgreSQL is authoritative for permissions.** Index payloads carry ACLs for fast filtering, but
retrieval re-validates against the database. This costs one query per search and removes a class
of stale-permission bugs.

**Character-based chunk sizes.** Sizes are in characters (about four per token) so chunking does not
depend on a tokenizer. The embedding model's own token limit (256 word pieces for MiniLM) is why
the default is 1,000 characters.

**Structure-aware chunking is the default.** Headings give chunks a topic and a citation title. The
fixed chunker stays available for comparison (`CHUNK_STRATEGY=fixed`).

**Section titles are embedded with the text.** Short chunks often omit the subject that the heading
names ("Rollback procedure").

**RRF instead of score blending.** BM25 and cosine scores live on different scales; ranks do not.

**In-memory index implementations.** They implement the same interfaces as the real adapters so the
pipeline, versioning and access control are testable without containers. They are not a substitute
for the adapter tests in `test_service_indexes.py`.

**Airflow tasks in a separate virtualenv.** Airflow 2.10 pins SQLAlchemy 1.4; ContextForge uses 2.x.
Airflow sequences, the virtualenv executes.

**Extractive fallback for the assistant.** Without an LLM the endpoint returns the best sentence of
each retrieved chunk with its citation. The LLM path validates that cited numbers exist and removes
others.

**Polars** is used only for per-category aggregation in the evaluation report; the rest of the data
handling is small enough not to need it.

**Not built:** OCR, external connectors, background job queue for the API, LLM-judged answer
evaluation, multilingual models, ingestion locking.
