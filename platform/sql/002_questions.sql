-- The question log (backend design §3): every question asked, how it was answered, and feedback on it.
-- Filter fields as columns and the whole log entry in `record`, as 001_k1.sql does, so the log can grow without a
-- migration. Idempotent: the init folder runs only on an empty volume, so an existing database gets this file
-- from `python -m backend.questions init`.

CREATE TABLE IF NOT EXISTS questions (
    question_id    text PRIMARY KEY,                 -- uuid4 hex, made by the service
    asked_at       timestamptz NOT NULL DEFAULT now(),
    question       text NOT NULL CHECK (length(question) BETWEEN 1 AND 500),
    mode           text NOT NULL CHECK (mode IN ('allow_fallback', 'exact')),
    forced_lane    text CHECK (forced_lane IN ('passages', 'well_facts', 'events', 'reasoning')),
    kind           text NOT NULL,                    -- the frame's kind, for counting question types
    report_type    text NOT NULL,                    -- the frame's report type
    lanes          text[] NOT NULL,                  -- the lanes that gave evidence
    fallback       boolean NOT NULL,
    answered_from  text CHECK (answered_from IN ('end_of_well', 'daily')),
    status         text NOT NULL,
    answer_text    text,
    calls          integer NOT NULL,
    seconds        real NOT NULL,
    record         jsonb NOT NULL                    -- the whole log entry, as backend/service.py writes it
);
CREATE INDEX IF NOT EXISTS questions_asked_at ON questions (asked_at);
CREATE INDEX IF NOT EXISTS questions_kind ON questions (kind);

CREATE TABLE IF NOT EXISTS question_feedback (
    feedback_id   bigserial PRIMARY KEY,
    question_id   text NOT NULL REFERENCES questions ON DELETE CASCADE,
    at            timestamptz NOT NULL DEFAULT now(),
    verdict       text NOT NULL CHECK (verdict IN ('right', 'wrong')),
    comment       text NOT NULL DEFAULT '' CHECK (length(comment) <= 2000)
);
