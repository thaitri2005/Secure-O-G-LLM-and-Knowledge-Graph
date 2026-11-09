-- K1 version 1 in PostgreSQL (Track C draft, C-C05).
-- One table per K1 record type (schemas/k1_*.schema.json). Each table keeps the IDs, links and filter fields as
-- columns and the whole K1 row in `record`, so nothing in the release is lost and the schema can grow without a
-- migration. IDs follow spec §5.11 as K1 version 1 writes them (D-54): file f<16 hex>, page <file>:p<n>,
-- table <file>:t<n>, parents <file>:s<n> / :t<n> / :f<n>, child chunk <parent>:c<n>.
-- A load replaces one release completely (delete the release, insert again): platform/load_k1.py.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE k1_releases (
    release            text PRIMARY KEY,                 -- release folder name, e.g. ak3-k1-candidate
    schema_version     text NOT NULL,
    manifest           jsonb NOT NULL,                   -- manifest.json as published
    sha256sums_sha256  char(64) NOT NULL,                -- SHA-256 of the release's SHA256SUMS file
    loaded_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE files (
    file_id        text PRIMARY KEY CHECK (file_id ~ '^f[0-9a-f]{16}$'),
    release        text NOT NULL REFERENCES k1_releases ON DELETE CASCADE,
    doc_id         text NOT NULL,
    document_type  text NOT NULL,
    sha256         char(64) NOT NULL UNIQUE,
    page_count     integer NOT NULL CHECK (page_count > 0),
    object_key     text,                                 -- original PDF in the object store; null until uploaded
    record         jsonb NOT NULL,
    -- D-54: the file ID is "f" plus the first 16 hex characters of the PDF's SHA-256
    CHECK (substr(file_id, 2) = substr(sha256, 1, 16))
);

CREATE TABLE pages (
    page_id   text PRIMARY KEY,
    file_id   text NOT NULL REFERENCES files ON DELETE CASCADE,
    page      integer NOT NULL CHECK (page >= 1),
    status    text NOT NULL CHECK (status IN ('ok', 'review', 'missing')),
    filtered_text_sha256 char(64) NOT NULL,              -- digest the page-rebuild check compares against
    record    jsonb NOT NULL,
    UNIQUE (file_id, page),
    CHECK (page_id = file_id || ':p' || page)
);

CREATE TABLE parents (
    parent_id      text PRIMARY KEY CHECK (parent_id ~ '^f[0-9a-f]{16}:[stf][1-9][0-9]*$'),
    file_id        text NOT NULL REFERENCES files ON DELETE CASCADE,
    type           text NOT NULL CHECK (type IN ('section', 'table', 'form')),
    pages          integer[] NOT NULL,
    document_type  text NOT NULL,
    record         jsonb NOT NULL,
    CHECK (starts_with(parent_id, file_id || ':'))
);

CREATE TABLE k1_tables (                                 -- "tables" would shadow the SQL word
    table_id    text PRIMARY KEY CHECK (table_id ~ '^f[0-9a-f]{16}:t[1-9][0-9]*$'),
    file_id     text NOT NULL REFERENCES files ON DELETE CASCADE,
    logical_id  text NOT NULL,
    pages       integer[] NOT NULL,
    num_rows    integer NOT NULL,
    num_cols    integer NOT NULL,
    record      jsonb NOT NULL,                          -- grid, cells, parts, join, rows_text, regions
    CHECK (starts_with(table_id, file_id || ':'))
);

CREATE TABLE forms (
    form_id   text PRIMARY KEY CHECK (form_id ~ '^f[0-9a-f]{16}:f[1-9][0-9]*$'),
    file_id   text NOT NULL REFERENCES files ON DELETE CASCADE,
    page      integer NOT NULL CHECK (page >= 1),
    verified  boolean NOT NULL,
    record    jsonb NOT NULL,                            -- fields (key-value pairs), method, template shares
    CHECK (starts_with(form_id, file_id || ':'))
);

CREATE TABLE chunks (
    chunk_id     text PRIMARY KEY CHECK (chunk_id ~ '^f[0-9a-f]{16}:[stf][1-9][0-9]*:c[0-9]+$'),
    parent_id    text NOT NULL REFERENCES parents ON DELETE CASCADE,
    file_id      text NOT NULL REFERENCES files ON DELETE CASCADE,
    table_id     text REFERENCES k1_tables ON DELETE CASCADE,
    form_id      text REFERENCES forms ON DELETE CASCADE,
    type         text NOT NULL CHECK (type IN ('text', 'table', 'form')),
    child_index  integer NOT NULL CHECK (child_index >= 0),
    seq          integer NOT NULL CHECK (seq >= 0),          -- line in chunks.jsonl: reading order, which page rebuild needs
    page         integer,
    pages        integer[] NOT NULL,
    text         text NOT NULL,
    sha256       char(64) NOT NULL,
    quality      text NOT NULL CHECK (quality IN ('ok', 'review')),
    well         text,                                   -- context.well (daily reports)
    report_date  text,                                   -- context.report_date as printed, e.g. 28-Aug-16
    record       jsonb NOT NULL,                         -- regions, source_spans, offsets, section path, ...
    UNIQUE (parent_id, child_index),
    CHECK (chunk_id = parent_id || ':c' || child_index),
    CHECK (starts_with(parent_id, file_id || ':'))
);

CREATE INDEX chunks_file ON chunks (file_id, seq);
CREATE INDEX chunks_well_date ON chunks (well, report_date);

-- Map from K1 version 0 chunk IDs (<doc_id>#c<nnnn>) to version 1: a release's legacy_chunk_ids.json (E30).
-- Gold data and old runs cite version 0 IDs; an old ID with no match is kept with method 'unmapped'.
CREATE TABLE chunk_id_map (
    old_chunk_id  text PRIMARY KEY CHECK (old_chunk_id ~ '#c[0-9]{4}$'),
    release       text NOT NULL REFERENCES k1_releases ON DELETE CASCADE,
    chunk_id      text REFERENCES chunks ON DELETE SET NULL,
    method        text NOT NULL CHECK (method IN ('exact', 'near', 'unmapped')),
    jaccard       real,
    CHECK ((method = 'unmapped') = (chunk_id IS NULL))
);

-- Vector store, if pgvector is chosen (C-D03, open). One row per chunk and embedding model, with the filter
-- fields copied from the chunk so retrieval can filter by well and report date in the same query.
-- Qwen3-Embedding-0.6B gives 1,024 dimensions. No approximate index yet: exact search over a few thousand
-- chunks is fast and never drops filtered results.
CREATE TABLE chunk_vectors (
    chunk_id         text NOT NULL REFERENCES chunks ON DELETE CASCADE,
    embedding_model  text NOT NULL,                      -- e.g. qwen3-embedding-0.6b-q8_0
    embedding        vector(1024) NOT NULL,
    file_id          text NOT NULL,
    document_type    text NOT NULL,
    well             text,
    report_date      text,
    PRIMARY KEY (chunk_id, embedding_model)
);
