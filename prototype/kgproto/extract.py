"""Extract typed claims from the AK-3 slice into PostgreSQL, and project reviewed claims as a Neo4j generation.

The ontology, output schema and validator come from the active profile file (ontology.PROFILE); this module
names no domain type. Only the slice and its document context are AK-3 specific.

Flow (design §5): extract -> deterministic validation (rejects are recorded by actor 'validator') ->
pending candidates wait for review (review.py) -> accepted claims are projected as a new generation ->
checks -> activation of the publication pointer. Nothing reaches the graph without a review decision.
"""
from __future__ import annotations

import hashlib
import json
import sys

from neo4j import GraphDatabase
from psycopg.types.json import Jsonb

from .config import MODEL, NEO4J_AUTH, NEO4J_URI, PDF_BUNDLE, REPORT_DOC
from .db import connect
from .llm import structured
from .ontology import PROFILE

# v1 pilot; v2 table/well/depth rules; v3 row-by-row tables; v4 row evidence + example (E4).
# v5 assembled the prompt generically and lost precision (E10); the oil_wells profile now carries the v4 text
# as its template, filled from the run's document context, so the version is v4 again.
PROMPT_VERSION = "extract-v4"
# Evaluation slice: the 8 pilot chunks (executive summary, drilling summary, casing tables, survey
# table, rig-time table, temperatures) plus the 7 other chunks that state the same gold facts.
SLICE = ["c0002", "c0010", "c0012", "c0013", "c0029", "c0037", "c0054", "c0055",
         "c0004", "c0005", "c0008", "c0022", "c0026", "c0028", "c0031"]
# What this run's document is about. It belongs to the document, not to the ontology.
DOCUMENT_CONTEXT = {
    "context": "The report is about well AK-3 of the Akutan geothermal project; it also mentions older wells TG-2 and TG-4.",
    "subject_examples": "AK-3, TG-2 or TG-4",
    "default_subject": "AK-3",
}
SYSTEM = PROFILE.extraction_prompt(DOCUMENT_CONTEXT)
SCHEMA = PROFILE.extraction_schema()


def chunks() -> list[dict]:
    return [c for c in json.loads((PDF_BUNDLE / "gdr_chunks.json").read_text(encoding="utf-8"))
            if c["doc_id"] == REPORT_DOC and c["chunk_id"].split("#")[1] in SLICE]


def passages(chunk: dict) -> list[tuple[str, str | None]]:
    """Return (passage, evidence row). Text goes whole; a table goes one data row at a time under its header,
    and that row is the claim's evidence (row-level table provenance)."""
    if chunk["type"] != "table":
        return [(chunk["text"], None)]
    lines = chunk["text"].splitlines()
    separator = next((i for i, line in enumerate(lines)
                      if line.startswith("|") and set(line.replace("|", "").strip()) <= {"-", " "}), None)
    if not separator:
        return [(chunk["text"], None)]
    head = lines[:separator + 1]
    return [("\n".join(head + [row]), row) for row in lines[separator + 1:] if row.startswith("|")]


def record(db, run_id: int, chunk_id: str, claim, valid, reason, latency: int, ok: bool) -> None:
    candidate = db.execute("INSERT INTO candidates (run_id, chunk_id, claim, valid, reason, latency_ms, output_ok) "
                           "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                           (run_id, chunk_id, Jsonb(claim) if claim is not None else None, valid, reason, latency,
                            ok)).fetchone()[0]
    if claim is not None and not valid:
        db.execute("INSERT INTO review_decisions (candidate_id, action, actor, note) VALUES (%s, 'reject', 'validator', %s)",
                   (candidate, reason))


def run_extraction() -> int:
    db = connect()
    run_id = db.execute("INSERT INTO extraction_runs (model, prompt_version, document) VALUES (%s, %s, %s) RETURNING id",
                        (MODEL, f"{PROMPT_VERSION} {PROFILE.id}", REPORT_DOC)).fetchone()[0]
    for chunk in chunks():
        short = chunk["chunk_id"].split("#")[1]
        for passage, row in passages(chunk):
            user = f"Section: {chunk['section']}\nPage: {chunk['page']}\nPassage:\n{passage}"
            output, latency = structured(SYSTEM, user, SCHEMA)
            if output is None:
                record(db, run_id, short, None, False, "unparseable model output", latency, False)
                continue
            if not output["claims"]:
                record(db, run_id, short, None, None, "no claims", latency, True)
            for claim in output["claims"]:
                if row is not None:
                    claim["quote"] = row
                reason = PROFILE.validate_claim(claim, chunk["text"])
                record(db, run_id, short, claim, reason is None, reason, latency, True)
            print(f"{short}: {len(output['claims'])} claims, {latency} ms", flush=True)
    db.execute("UPDATE extraction_runs SET finished_at = now() WHERE id = %s", (run_id,))
    return run_id


def project(run_id: int, label: str) -> int:
    """Build a new generation from the run's accepted claims, check it, and return its ID (not yet active)."""
    db = connect()
    generation = db.execute("INSERT INTO generations (run_id, label) VALUES (%s, %s) RETURNING id",
                            (run_id, label)).fetchone()[0]
    rows = db.execute("SELECT c.chunk_id, c.claim FROM candidates c JOIN review_decisions r ON r.candidate_id = c.id "
                      "WHERE c.run_id = %s AND r.action = 'accept'", (run_id,)).fetchall()
    label, field = PROFILE.subject["graph_label"], PROFILE.subject_field
    expected: set[tuple[str, str]] = set()  # the frozen accepted set: (claim ID, evidence chunk ID)
    with GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH) as driver, driver.session() as session:
        for chunk_id, claim in rows:
            subject = PROFILE.subject_key(claim[field])
            context = {name: PROFILE.context_key(name, claim.get(name)) for name in PROFILE.context_fields}
            key = json.dumps([generation, subject, claim["property"], claim["qualifier"],
                              *context.values(), claim["value"]])
            claim_id = hashlib.sha1(key.encode()).hexdigest()[:16]
            expected.add((claim_id, f"{REPORT_DOC}#{chunk_id}"))
            # The label comes from the validated profile (a trusted asset), never from model output.
            session.run(
                "MATCH (d:Document {id: $doc}) MATCH (ch:Chunk {id: $chunk}) "
                f"MERGE (w:{label} {{id: $subject_id}}) ON CREATE SET w.name = $name, w.project_document = $doc "
                "MERGE (d)-[:DESCRIBES]->(w) "
                "MERGE (c:Claim {id: $claim_id}) ON CREATE SET c.generation = $generation, c.property = $property, "
                "  c.qualifier = $qualifier, c.value = $value, c.unit = $unit, c.extraction_run = $run, "
                "  c.profile = $profile, c += $context "
                "MERGE (c)-[:ABOUT]->(w) "
                "MERGE (c)-[s:SUPPORTED_BY]->(ch) ON CREATE SET s.quote = $quote",
                doc=REPORT_DOC, chunk=f"{REPORT_DOC}#{chunk_id}",
                subject_id=f"{label.lower()}:{REPORT_DOC}:{subject}", name=claim[field],
                claim_id=claim_id, generation=generation,
                property=claim["property"], qualifier=claim["qualifier"], value=claim["value"], unit=claim["unit"],
                run=run_id, profile=PROFILE.id, context=context, quote=claim["quote"])
        projected = [(r["claim"], r["chunk"]) for r in session.run(
            "MATCH (c:Claim {generation: $g}) OPTIONAL MATCH (c)-[:SUPPORTED_BY]->(ch:Chunk) "
            "RETURN c.id AS claim, ch.id AS chunk", g=generation)]
    problems = generation_problems(expected, projected)
    digest = hashlib.sha256(json.dumps(sorted(expected)).encode()).hexdigest()
    db.execute("UPDATE generations SET claims = %s, evidence = %s, checks_passed = %s, expected_digest = %s, "
               "problems = %s WHERE id = %s",
               (len({c for c, _ in projected}), sum(1 for _, ch in projected if ch), not problems, digest,
                Jsonb(problems), generation))
    return generation


def generation_problems(expected: set[tuple[str, str]], projected: list[tuple[str, str | None]]) -> list[str]:
    """Compare the projected generation with the frozen accepted set, exactly (E9: counts alone let a partial
    projection pass). Every expected claim and evidence link must be present, and nothing else."""
    actual = {(claim, chunk) for claim, chunk in projected if chunk}
    problems = [f"missing {claim} <- {chunk}" for claim, chunk in sorted(expected - actual)]
    problems += [f"unexpected {claim} <- {chunk}" for claim, chunk in sorted(actual - expected)]
    problems += [f"claim without evidence {claim}" for claim, chunk in projected if not chunk]
    return problems


def activate(generation: int) -> None:
    """Switch the publication pointer, only to a generation whose checks passed."""
    db = connect()
    if not db.execute("SELECT checks_passed FROM generations WHERE id = %s", (generation,)).fetchone()[0]:
        raise ValueError(f"generation {generation} failed its checks")
    db.execute("INSERT INTO publication (workspace, active_generation) VALUES ('default', %s) "
               "ON CONFLICT (workspace) DO UPDATE SET active_generation = EXCLUDED.active_generation", (generation,))
    db.execute("UPDATE generations SET activated_at = now() WHERE id = %s", (generation,))


if __name__ == "__main__":
    print(f"run {run_extraction()}" if sys.argv[1:] != ["--help"] else __doc__)
