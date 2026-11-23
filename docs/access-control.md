# Access control

## Model

- Every document has a `tenant_id`, an `owner_id` and `allowed_groups`.
- Every user has a `tenant_id` and one or more roles: `administrator`, `engineering`, `product`,
  `operations`, `general_employee`.
- A user may read a document when the tenant matches **and** (the user is an administrator, or
  owns the document, or one of their roles is in `allowed_groups`).
- A document with no allowed groups is visible to its owner and administrators only. Files that
  match no rule in `config/access_policies.yaml` get the default policy (administrators only).

Administrators are scoped to their tenant; the tenant check comes first.

## Enforcement layers

1. **In the index query.** The tenant/group/owner filter is part of the Qdrant filter and the
   OpenSearch `bool.filter`, so restricted chunks never leave the index for other users.
2. **After ranking.** The retriever re-checks each hit against PostgreSQL. This covers stale index
   payloads (for example an ACL changed but not yet re-indexed) and deleted or superseded
   documents. `test_stale_index_payload_cannot_bypass_current_database_acl` exercises it.
3. **Direct lookup.** `GET /documents/{id}` returns 404 for both missing and forbidden documents.
4. **Assistant.** `/chat` calls the same retriever. The model only receives chunks the user may
   read, so there is nothing restricted to leak in the answer.

Tests in `tests/integration/test_access_enforcement.py` cover keyword, vector and hybrid search
(with and without reranking), document listing, direct lookup, the assistant, tenant isolation and
the admin-only endpoints. They run against the in-memory indexes; the Qdrant and OpenSearch filters
are covered by `test_service_indexes.py`, which needs running services.

## Permissions are applied at ingestion

ACLs come from `config/access_policies.yaml` and are copied onto chunks when they are indexed.
Changing the file changes the stored ACL on the next ingestion run (`acl_update`). Until then the
database ACL is already authoritative for validation, so access can be revoked immediately but
newly granted access appears after re-indexing.

## Authentication

Development only: each request carries `X-API-Key`. `config/users.yaml` stores SHA-256 digests of
keys and the digests are compared in constant time. The sample users' keys are `cf-dev-alice`,
`cf-dev-bob`, `cf-dev-carol`, `cf-dev-dave`, `cf-dev-erin` (all tenant `halvorsen`) and
`cf-dev-frank` (tenant `northwind-labs`). They are fictional.

## Security limitations

- API keys are static, unsalted-digest, have no expiry or rotation and are sent in a header over
  plain HTTP in the default setup. Use TLS and a real identity provider (OIDC) in production.
- OpenSearch runs with its security plugin disabled and Qdrant has no API key in the compose file.
  Anyone who can reach those ports can read every chunk. Do not expose them.
- Roles come from a static file. There is no group sync, no audit log of who searched for what,
  and no rate limiting.
- ACL rules are path-based. Documents are not classified by content.
- Raw files in MinIO are not encrypted per tenant.
- Embeddings can leak information about their source text; treat the vector index as sensitive.
- `/metrics` and `/health` are unauthenticated.
