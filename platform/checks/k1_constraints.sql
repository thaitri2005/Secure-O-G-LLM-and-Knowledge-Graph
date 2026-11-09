-- Smoke check for platform/sql/001_k1.sql (C-C05). Changes nothing: everything runs in one transaction that is
-- rolled back at the end. Run it against the Docker PostgreSQL:
--
--   docker compose -f platform/docker-compose.yml exec -T postgres psql -U kg -d kg -v ON_ERROR_STOP=1 < platform/checks/k1_constraints.sql
--
-- Expected: one "PASS" line per check and "ALL CHECKS PASSED" at the end. A FAIL line names the rule that let a
-- bad row in.

BEGIN;

-- One valid release, file, page, parent and chunk, using the ID from spec §5.11 / D-54.
INSERT INTO k1_releases (release, schema_version, manifest, sha256sums_sha256)
VALUES ('check', 'k1.v1', '{}', repeat('0', 64));

INSERT INTO files (file_id, release, doc_id, document_type, sha256, page_count, record)
VALUES ('f62efbee00767a3e7', 'check', 'gdr882_ak3_eowr', 'eowr',
        '62efbee00767a3e7' || repeat('0', 48), 29, '{}');

INSERT INTO pages (page_id, file_id, page, status, filtered_text_sha256, record)
VALUES ('f62efbee00767a3e7:p2', 'f62efbee00767a3e7', 2, 'ok', repeat('0', 64), '{}');

INSERT INTO parents (parent_id, file_id, type, pages, document_type, record)
VALUES ('f62efbee00767a3e7:s6', 'f62efbee00767a3e7', 'section', '{2}', 'eowr', '{}');

INSERT INTO chunks (chunk_id, parent_id, file_id, type, child_index, page, pages, text, sha256, quality, record)
VALUES ('f62efbee00767a3e7:s6:c0', 'f62efbee00767a3e7:s6', 'f62efbee00767a3e7', 'text', 0, 2, '{2}',
        'drilled to 1,955 feet', repeat('0', 64), 'ok', '{}');

DO $$ BEGIN RAISE NOTICE 'PASS  valid rows load'; END $$;

-- Each bad row below must be refused. expect_refused runs one statement inside a savepoint-like block and
-- reports PASS when PostgreSQL rejects it.
CREATE FUNCTION pg_temp.expect_refused(label text, stmt text) RETURNS void AS $$
BEGIN
    EXECUTE stmt;
    RAISE EXCEPTION 'FAIL  % (the row was accepted)', label USING ERRCODE = 'P0001';
EXCEPTION
    WHEN integrity_constraint_violation OR check_violation OR foreign_key_violation
         OR unique_violation OR not_null_violation OR data_exception THEN
        RAISE NOTICE 'PASS  % refused', label;
END $$ LANGUAGE plpgsql;

SELECT pg_temp.expect_refused('file ID that is not f + first 16 hex of the SHA-256',
    $s$INSERT INTO files (file_id, release, doc_id, document_type, sha256, page_count, record)
       VALUES ('f0000000000000000', 'check', 'x', 'eowr', '1111111111111111' || repeat('0', 48), 1, '{}')$s$);

SELECT pg_temp.expect_refused('page ID that does not match its page number',
    $s$INSERT INTO pages (page_id, file_id, page, status, filtered_text_sha256, record)
       VALUES ('f62efbee00767a3e7:p9', 'f62efbee00767a3e7', 3, 'ok', repeat('0', 64), '{}')$s$);

SELECT pg_temp.expect_refused('chunk ID that does not match its child index',
    $s$INSERT INTO chunks (chunk_id, parent_id, file_id, type, child_index, pages, text, sha256, quality, record)
       VALUES ('f62efbee00767a3e7:s6:c5', 'f62efbee00767a3e7:s6', 'f62efbee00767a3e7', 'text', 1, '{2}',
               'x', repeat('0', 64), 'ok', '{}')$s$);

SELECT pg_temp.expect_refused('chunk whose parent does not exist',
    $s$INSERT INTO chunks (chunk_id, parent_id, file_id, type, child_index, pages, text, sha256, quality, record)
       VALUES ('f62efbee00767a3e7:s7:c0', 'f62efbee00767a3e7:s7', 'f62efbee00767a3e7', 'text', 0, '{2}',
               'x', repeat('0', 64), 'ok', '{}')$s$);

SELECT pg_temp.expect_refused('chunk ID in the old version 0 format',
    $s$INSERT INTO chunks (chunk_id, parent_id, file_id, type, child_index, pages, text, sha256, quality, record)
       VALUES ('gdr882_ak3_eowr#c0002', 'f62efbee00767a3e7:s6', 'f62efbee00767a3e7', 'text', 1, '{2}',
               'x', repeat('0', 64), 'ok', '{}')$s$);

SELECT pg_temp.expect_refused('vector with the wrong number of dimensions',
    $s$INSERT INTO chunk_vectors (chunk_id, embedding_model, embedding, file_id, document_type)
       VALUES ('f62efbee00767a3e7:s6:c0', 'check', '[1,2,3]', 'f62efbee00767a3e7', 'eowr')$s$);

-- Tracing a cited chunk back to its file and page: the join a citation viewer will use.
DO $$
DECLARE found text;
BEGIN
    SELECT f.doc_id || ' page ' || p.page INTO found
    FROM chunks c
    JOIN files f ON f.file_id = c.file_id
    JOIN pages p ON p.file_id = c.file_id AND p.page = c.page
    WHERE c.chunk_id = 'f62efbee00767a3e7:s6:c0';
    IF found = 'gdr882_ak3_eowr page 2' THEN
        RAISE NOTICE 'PASS  chunk traces back to %', found;
    ELSE
        RAISE EXCEPTION 'FAIL  chunk traced to %', coalesce(found, 'nothing');
    END IF;
END $$;

-- Deleting a release removes everything loaded with it.
DELETE FROM k1_releases WHERE release = 'check';
DO $$
BEGIN
    IF (SELECT count(*) FROM files) + (SELECT count(*) FROM pages) + (SELECT count(*) FROM parents)
       + (SELECT count(*) FROM chunks) = 0 THEN
        RAISE NOTICE 'PASS  deleting a release removes its rows';
    ELSE
        RAISE EXCEPTION 'FAIL  rows left after deleting the release';
    END IF;
END $$;

DO $$ BEGIN RAISE NOTICE 'ALL CHECKS PASSED'; END $$;

ROLLBACK;
