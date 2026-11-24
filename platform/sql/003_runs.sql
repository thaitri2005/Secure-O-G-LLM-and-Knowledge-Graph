-- Run records of platform/run_release.py (backend design §6, specification §4.3).
-- One row per run of the runner: the release, when it started and finished, whether it succeeded, and the whole
-- record (release digest, git commit, embedding model, counts and seconds per step) in `record`.
-- Idempotent, because the runner applies it before writing and the init folder runs only on an empty volume.

CREATE TABLE IF NOT EXISTS runs (
    run_id       text PRIMARY KEY,                     -- <release>-<UTC start time>, made by the runner
    release      text NOT NULL,                        -- not a reference: a run can fail before the release loads
    started_at   timestamptz NOT NULL,
    finished_at  timestamptz,
    status       text NOT NULL,                        -- 'succeeded' or 'failed'
    record       jsonb NOT NULL
);

CREATE INDEX IF NOT EXISTS runs_release ON runs (release, started_at);
