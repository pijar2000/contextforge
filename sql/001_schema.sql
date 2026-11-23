-- PostgreSQL schema for ContextForge. Mirrors src/contextforge/storage/models.py.
-- Applied automatically by the postgres container on first start (docker-entrypoint-initdb.d).

CREATE TABLE IF NOT EXISTS documents (
    document_id       VARCHAR(64) PRIMARY KEY,
    tenant_id         VARCHAR(64)  NOT NULL,
    source_name       VARCHAR(128) NOT NULL,
    source_path       TEXT         NOT NULL,
    file_name         TEXT         NOT NULL,
    file_type         VARCHAR(16)  NOT NULL,
    size_bytes        INTEGER      NOT NULL DEFAULT 0,
    modified_at       TIMESTAMPTZ,
    content_hash      VARCHAR(64)  NOT NULL,
    current_version   INTEGER      NOT NULL DEFAULT 1,
    indexed_version   INTEGER,
    status            VARCHAR(16)  NOT NULL,
    owner_id          VARCHAR(128) NOT NULL,
    allowed_groups    JSONB        NOT NULL DEFAULT '[]'::jsonb,
    title             TEXT,
    last_error        TEXT,
    first_seen_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_ingested_at  TIMESTAMPTZ,
    deleted_at        TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_documents_tenant_id ON documents (tenant_id);
CREATE INDEX IF NOT EXISTS ix_documents_status ON documents (status);
CREATE INDEX IF NOT EXISTS ix_documents_source ON documents (tenant_id, source_name, source_path);

CREATE TABLE IF NOT EXISTS document_versions (
    document_id      VARCHAR(64) NOT NULL REFERENCES documents (document_id),
    version          INTEGER     NOT NULL,
    content_hash     VARCHAR(64) NOT NULL,
    object_key       TEXT,
    status           VARCHAR(16) NOT NULL,  -- pending|indexed|failed|empty|superseded
    chunk_count      INTEGER     NOT NULL DEFAULT 0,
    page_count       INTEGER,
    chunk_strategy   VARCHAR(16),
    embedding_model  VARCHAR(128),
    error            TEXT,
    run_id           VARCHAR(64),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    indexed_at       TIMESTAMPTZ,
    PRIMARY KEY (document_id, version)
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id          VARCHAR(128) PRIMARY KEY,
    document_id       VARCHAR(64)  NOT NULL,
    document_version  INTEGER      NOT NULL,
    chunk_index       INTEGER      NOT NULL,
    page_number       INTEGER,
    section_title     TEXT,
    text              TEXT         NOT NULL,
    char_count        INTEGER      NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_chunks_document_id ON chunks (document_id);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id                VARCHAR(64) PRIMARY KEY,
    tenant_id             VARCHAR(64) NOT NULL,
    trigger               VARCHAR(32) NOT NULL,
    status                VARCHAR(16) NOT NULL,
    started_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at           TIMESTAMPTZ,
    docs_scanned          INTEGER NOT NULL DEFAULT 0,
    docs_processed        INTEGER NOT NULL DEFAULT 0,
    docs_skipped          INTEGER NOT NULL DEFAULT 0,
    docs_failed           INTEGER NOT NULL DEFAULT 0,
    docs_deleted          INTEGER NOT NULL DEFAULT 0,
    chunks_created        INTEGER NOT NULL DEFAULT 0,
    embeddings_generated  INTEGER NOT NULL DEFAULT 0,
    duration_seconds      DOUBLE PRECISION,
    details               JSONB NOT NULL DEFAULT '{}'::jsonb
);
