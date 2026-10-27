"""PostgreSQL workflow store for the prototype: runs, candidates, reviews, graph generations and the question log.

PostgreSQL is authoritative (design §4.2); Neo4j holds a rebuildable projection of one activated generation.
"""
import psycopg

from .config import POSTGRES_DSN

SCHEMA = """
CREATE TABLE IF NOT EXISTS extraction_runs (
    id serial PRIMARY KEY, model text, prompt_version text, document text,
    started_at timestamptz DEFAULT now(), finished_at timestamptz);
CREATE TABLE IF NOT EXISTS candidates (
    id serial PRIMARY KEY, run_id int REFERENCES extraction_runs, chunk_id text, claim jsonb,
    valid boolean, reason text, latency_ms int, output_ok boolean);
CREATE TABLE IF NOT EXISTS review_decisions (
    id serial PRIMARY KEY, candidate_id int UNIQUE REFERENCES candidates, action text, actor text, note text,
    decided_at timestamptz DEFAULT now());
CREATE TABLE IF NOT EXISTS generations (
    id serial PRIMARY KEY, run_id int REFERENCES extraction_runs, label text, claims int, evidence int,
    checks_passed boolean, created_at timestamptz DEFAULT now(), activated_at timestamptz);
ALTER TABLE generations ADD COLUMN IF NOT EXISTS expected_digest text;
ALTER TABLE generations ADD COLUMN IF NOT EXISTS problems jsonb;
CREATE TABLE IF NOT EXISTS publication (
    workspace text PRIMARY KEY, active_generation int REFERENCES generations);
CREATE TABLE IF NOT EXISTS questions_log (
    id serial PRIMARY KEY, asked_at timestamptz DEFAULT now(), question text, plan jsonb,
    status text, answer jsonb, latency_ms int, generation int);
"""


def connect() -> psycopg.Connection:
    connection = psycopg.connect(POSTGRES_DSN, autocommit=True)
    connection.execute(SCHEMA)
    return connection


def active_generation(db: psycopg.Connection) -> int | None:
    row = db.execute("SELECT active_generation FROM publication WHERE workspace = 'default'").fetchone()
    return row[0] if row else None
