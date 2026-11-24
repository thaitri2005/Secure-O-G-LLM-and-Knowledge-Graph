"""Run one K1 release into the stores the application answers from (backend design §6, B2).

    python platform/run_release.py data/interim/k1/ak3-k1-v1-candidate
    python platform/run_release.py <release folder> --skip-vectors --skip-graphs

Eight steps, called in order. A failed check stops the run, exits 1 and names the step; each loader rolls back its
own transaction, so a failed run leaves that store as it was.

| Step | Uses | Stops the run when |
|---|---|---|
| 1. Validate | Track A's validator (graph_builder.corpus.k1_validate) | any validator error |
| 2. Load chunks | platform/load_k1.py | row counts differ from the manifest, or a page does not rebuild |
| 3. Embed | platform/embed_k1.py `embed`, then `check` (needs the embedding server) | vectors differ from chunks, or the SQL and in-memory searches differ |
| 4. Build the event graph | graphrag.events.build_events on the release, no model call | a daily-report file with an operations table gives no event |
| 5. Load the event region | platform/load_events_neo4j.py | its read-back, plan replay or Cypher totals differ |
| 6. Build the fact graph | the recorded graph moved onto the release's chunk IDs, the recorded graph as it is, or graphrag.tables and graphrag.factgraph on the release | a relationship is dangling, or the file breaks the region's design |
| 7. Load the fact region | platform/load_facts_neo4j.py | its counts, read-back or event region differ |
| 8. Record the run | one row in `runs` (platform/sql/003_runs.sql, applied here) | — |

Step 6 starts from the fact graph the engine answers from, `graphrag/results/E32_fact_graph.graph.json`: 207 facts
of three end-of-well reports, read by Qwen3-4B (a model call, on the GPU) and by K2's table mappings, citing K1
version 0 chunk IDs. Three choices, by `--facts`:

| `--facts` | Fact graph | Default |
|---|---|---|
| `mapped` | the recorded graph moved onto the release's chunk IDs through its `legacy_chunk_ids.json` and checked again on the new text (graphrag.factgraph `map_to_release`, no model call); a fact that cannot move keeps its old ID and is counted | when the release holds a legacy map |
| `recorded` | the recorded graph as it is, on K1 version 0 IDs, so the stores hold no passage for its facts | otherwise |
| `tables` | built from the release's end-of-well tables with K2's mappings (no model call; on AK-3 alone that was 43 facts) | — |

The non-productive report (appendix 23) is read from the release when it holds it, else from the corpus export
named by `--appendices`.

`--skip-vectors` skips step 3, and `--skip-graphs` steps 4 to 7. Step 2 keeps a release the store already holds
with the same SHA256SUMS digest and only checks it, so a second run changes nothing and keeps the vectors.
`--reload` replaces it anyway; its vectors then go with it (chunk_vectors cascades from chunks), so `--reload` with
`--skip-vectors` leaves the release with no vectors. Connection settings: BACKEND_DSN, NEO4J_URI, NEO4J_USER,
NEO4J_PASSWORD, with the local compose values as defaults. Files the run writes go under `--out/<run_id>/`; what a
step decided (kept or loaded, which fact graph) goes into the run record's `notes`.
"""
from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import psycopg  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

import embed_k1  # noqa: E402
import load_events_neo4j  # noqa: E402
import load_facts_neo4j  # noqa: E402
import load_k1  # noqa: E402
from graph_builder.corpus.k1_validate import GROUPS, SUMS, validate_k1  # noqa: E402

from graphrag import events as event_graph  # noqa: E402
from graphrag.data import appendix_chunks_path, document_key, load_chunks  # noqa: E402
from graphrag.factgraph import LEGACY_MAP, map_to_release, to_graph  # noqa: E402
from graphrag.ontology import load as load_k2, table_rows  # noqa: E402
from graphrag.scoring import normalize  # noqa: E402
from graphrag.tables import extract  # noqa: E402
from graphrag.validate import validate  # noqa: E402

DSN = os.environ.get("BACKEND_DSN", "postgresql://kg:platform-dev@127.0.0.1:5434/kg")
RUNS_SQL = HERE / "sql/003_runs.sql"
OUT = ROOT / "data/interim/release_runs"
NPT = "-appx-23-"   # the non-productive-time report's doc IDs, as graphrag.events finds them


class StepFailed(Exception):
    """A check that stops the run."""


@dataclass
class Run:
    release: Path
    name: str
    out: Path
    dsn: str = DSN
    neo4j: tuple[str, str, str] = (load_events_neo4j.URI, load_events_neo4j.USER, load_events_neo4j.PASSWORD)
    appendices: Path = event_graph.OLD_EXPORT
    facts: str = "recorded"
    endpoint: str = "local-embed"
    embedding_model: str = embed_k1.MODEL
    reload: bool = False
    replaces: str | None = None   # another release in the store that holds the same files and must go first
    written: dict[str, Path] = field(default_factory=dict)   # files the steps hand on to later steps
    notes: dict[str, str] = field(default_factory=dict)      # what a step decided, for the run record

    def note(self, step: str, text: str) -> None:
        self.notes[step] = text
        print(f"  {text}")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def step_validate(run: Run) -> dict:
    errors = validate_k1(run.release)
    if errors:
        raise StepFailed(f"Track A's validator found {len(errors)} problems: " + "; ".join(errors[:5]))
    return dict(json.loads((run.release / "manifest.json").read_text(encoding="utf-8"))["counts"])


def step_load_chunks(run: Run) -> dict:
    package = load_k1.read_package(run.release)
    with psycopg.connect(run.dsn) as conn, conn.cursor() as cur:   # an exception inside rolls the load back
        cur.execute("SELECT sha256sums_sha256 FROM k1_releases WHERE release = %s", (run.name,))
        stored = cur.fetchone()
        if stored and stored[0] == package["sums_sha256"] and not run.reload:
            run.note("load chunks", "the store already holds this release with the same SHA256SUMS digest: kept, "
                     "with its vectors, and checked (--reload replaces it)")
        else:
            if run.replaces and run.replaces != run.name:
                # A file belongs to one release (files.file_id is a key), so a newer release of the same reports
                # cannot be loaded beside the older one. Same transaction: a failed load keeps the older release.
                cur.execute("DELETE FROM k1_releases WHERE release = %s", (run.replaces,))
                run.note("replaces", f"release {run.replaces} removed" if cur.rowcount else f"no release {run.replaces} in the store")
            load_k1.load(cur, run.name, package)
            same = stored and stored[0] == package["sums_sha256"]
            replaced = (", replacing the same release (--reload)" if same
                        else ", replacing a different one of the same name" if stored else "")
            run.note("load chunks", "release loaded" + replaced)
        problems = load_k1.check(cur, run.name, package)
        if problems:
            raise StepFailed(f"{len(problems)} problems reading the release back: " + "; ".join(problems[:5]))
    return {**{name: len(package[name]) for name in GROUPS}, "legacy_ids": len(package["legacy"])}


def step_embed(run: Run) -> dict:
    args = argparse.Namespace(dsn=run.dsn, release=run.name, endpoint=run.endpoint, model=run.embedding_model,
                              batch=16, k=5)
    if embed_k1.embed(args) != 0:
        raise StepFailed("the vectors stored are not one per chunk")
    if embed_k1.check(args) != 0:
        raise StepFailed("pgvector and the in-memory search give different top 5")
    with psycopg.connect(run.dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM chunk_vectors v JOIN files f USING (file_id) WHERE f.release = %s "
                    "AND v.embedding_model = %s", (run.name, run.embedding_model))
        return {"vectors": cur.fetchone()[0]}


def event_inputs(release: Path, appendices: Path) -> tuple[list, list[dict], dict]:
    """As graphrag.events.load_k1_inputs, with the release named: daily-report chunks and tables, each page's report
    date from `context.report_date`, and the non-productive report from the release or else the corpus export."""
    rows = read_jsonl(release / "chunks.jsonl")
    tables = read_jsonl(release / "tables.jsonl")
    daily = sorted({r["doc_id"] for r in rows if "dailyreport" in r["doc_id"]})
    dates = {}
    for r in rows:
        date = (r.get("context") or {}).get("report_date")
        if r["doc_id"] in daily and date:
            for page in r.get("pages") or [r["page"]]:
                dates.setdefault((r["doc_id"], page), normalize(date))
    npt = sorted({r["doc_id"] for r in rows if NPT in r["doc_id"]})
    npt_path = release / "chunks.jsonl"
    if not npt:
        npt_path = appendix_chunks_path(appendices) if (appendices / "CURRENT.json").is_file() else appendices / "chunks.jsonl"
        if not npt_path.is_file():
            raise StepFailed(f"the release has no non-productive report and {npt_path} does not exist: name a corpus "
                             "export holding appendix 23 with --appendices")
        npt = sorted({r["doc_id"] for r in read_jsonl(npt_path) if NPT in r["doc_id"]})
        tables += read_jsonl(npt_path.parent / "tables.jsonl")
    chunks = load_chunks(daily, release / "chunks.jsonl") + load_chunks(npt, npt_path)
    return chunks, [t for t in tables if t["doc_id"] in daily or t["doc_id"] in npt], dates


def is_operations_table(table: dict) -> bool:
    """The test graphrag.events.build_events uses to read a table as operations."""
    rows = table_rows(table)
    head = " ".join(rows[0]) if rows else ""
    return "Elapsed" in head and "Code" in head


def step_build_events(run: Run) -> dict:
    chunks, tables, dates = event_inputs(run.release, run.appendices)
    events, stats = event_graph.build_events(chunks, tables, dates)
    records = read_jsonl(run.release / "files.jsonl")
    files = {f["file_id"]: f["doc_id"] for f in records}
    daily = sorted(f["doc_id"] for f in records if f["document_type"] == "daily_report")
    with_operations = {t["doc_id"] for t in tables if is_operations_table(t)}
    by_file = {doc: 0 for doc in daily}
    for e in events:
        for doc in {files.get(document_key(c), document_key(c)) for c in e.chunks}:
            by_file[doc] = by_file.get(doc, 0) + 1
    empty = [doc for doc in daily if doc in with_operations and not by_file[doc]]
    if empty:
        raise StepFailed(f"no event from {len(empty)} daily-report files with an operations table: {', '.join(empty)}")
    path = run.out / "events.json"
    path.write_text(json.dumps({"method": "operations tables and the non-productive report, no model call",
                                "llm_calls": 0, "source": f"K1 release {run.name}", "wells": [event_graph.WELL],
                                "build": stats, "events": [asdict(e) for e in events]}, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    run.written["events"] = path
    return {"events": len(events), "days": len({e.date for e in events}), "build": stats, "events_by_file": by_file,
            "daily_files_without_operations_table": [doc for doc in daily if doc not in with_operations]}


def step_load_events(run: Run) -> dict:
    try:
        s = load_events_neo4j.load(run.written["events"], None, None, *run.neo4j, run.dsn)
    except load_events_neo4j.CheckFailed as failure:
        raise StepFailed(str(failure)) from None
    return {k: s[k] for k in ("well", "days", "events", "chunks", "events_same", "plans_same", "plans", "codes_same",
                              "codes", "npt", "k1_chunks", "k1_chunks_missing_in_postgres")}


def release_fact_graph(release: Path) -> tuple[dict, dict]:
    """The fact graph from the release's end-of-well tables by K2's mappings, checked strictly; no model call."""
    eow = {f["doc_id"] for f in read_jsonl(release / "files.jsonl") if f["document_type"] == "eowr"}
    chunks = load_chunks(sorted(eow), release / "chunks.jsonl")
    facts = extract(chunks, load_k2(), release / "tables.jsonl")
    kept, rejected = validate(facts, {c.id: c.text for c in chunks}, strict=True)
    return to_graph(kept), {"facts_read": len(facts), "facts_kept": len(kept), "facts_rejected": rejected}


def default_facts(release: Path) -> str:
    """`mapped` when the release holds a legacy map to move the recorded facts with, else `recorded`."""
    return "mapped" if (release / LEGACY_MAP).is_file() else "recorded"


def step_build_facts(run: Run) -> dict:
    if run.facts == "recorded":
        path = load_facts_neo4j.GRAPH
        graph = json.loads(path.read_text(encoding="utf-8"))
        run.note("build facts", f"the recorded fact graph {path.name} is loaded, not one built from this release: "
                 "it holds facts Qwen3-4B extracted (a model call) from three end-of-well reports, and its chunk IDs "
                 "are K1 version 0; --facts tables builds one from the release's tables with no model call")
        source = {"source": f"recorded: {path.relative_to(ROOT).as_posix()}"}
    elif run.facts == "mapped":
        graph, counts = map_to_release(run.release, load_facts_neo4j.GRAPH)
        source = {"source": f"recorded {counts['source_graph']} moved onto release {run.name}'s chunk IDs by its "
                            f"legacy map, no model call",
                  **{k: counts[k] for k in ("facts", "facts_on_new_ids", "facts_on_old_ids", "chunks_cited",
                                            "chunks_mapped")}}
        run.note("build facts", f"recorded fact graph moved onto the release's chunk IDs, no model call: "
                 f"{counts['facts_on_new_ids']} of {counts['facts']} facts on its IDs, the rest on their old IDs "
                 f"({', '.join(f'{k} {v}' for k, v in counts['facts_on_old_ids'].items()) or 'none'})")
        path = run.out / "facts.graph.json"
        path.write_text(json.dumps({**counts, **graph}, indent=1) + "\n", encoding="utf-8", newline="\n")
    else:
        graph, source = release_fact_graph(run.release)
        source = {"source": f"K2 table mappings on release {run.name}, no model call", **source}
        run.note("build facts", f"fact graph built from the release's end-of-well tables by K2's mappings, no model "
                 f"call: {source['facts_kept']} facts kept of {source['facts_read']}")
        path = run.out / "facts.graph.json"
        path.write_text(json.dumps(graph, indent=1) + "\n", encoding="utf-8", newline="\n")
    keys = {(n["label"], n["key"]) for n in graph["nodes"]}
    dangling = sum(tuple(r["from"]) not in keys or tuple(r["to"]) not in keys for r in graph["relationships"])
    problems = load_facts_neo4j.check_file(graph)
    if dangling or problems:
        raise StepFailed(f"{dangling} dangling relationships; " + "; ".join(problems[:5]))
    run.written["facts"] = path
    return {**source, "nodes": dict(sorted(Counter(n["label"] for n in graph["nodes"]).items())),
            "relationships": dict(sorted(Counter(r["type"] for r in graph["relationships"]).items())), "dangling": 0}


def step_load_facts(run: Run) -> dict:
    try:
        s = load_facts_neo4j.load(run.written["facts"], *run.neo4j, run.dsn)
    except load_facts_neo4j.CheckFailed as failure:
        raise StepFailed(str(failure)) from None
    return {k: s[k] for k in ("wells", "nodes", "relationships", "facts_same", "facts", "event_region", "k1_chunks",
                              "k1_chunks_missing_in_postgres")}


STEPS = [("validate", step_validate), ("load chunks", step_load_chunks), ("embed", step_embed),
         ("build events", step_build_events), ("load events", step_load_events), ("build facts", step_build_facts),
         ("load facts", step_load_facts)]
GRAPH_STEPS = {"build events", "load events", "build facts", "load facts"}


def git_commit() -> str | None:
    try:
        done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10)
        return done.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def record_run(dsn: str, record: dict) -> dict | None:
    """Step 8: write the run's row, and compare its counts with the last successful run of the same release digest
    made with the same options. Returns that run's ID and whether the counts are the same, or None when there was
    none."""
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(RUNS_SQL.read_text(encoding="utf-8"))
        cur.execute("SELECT run_id, record -> 'counts' FROM runs WHERE release = %s AND status = 'succeeded' "
                    "AND record ->> 'sha256sums_sha256' = %s AND record -> 'skipped' = %s "
                    "AND record ->> 'facts' IS NOT DISTINCT FROM %s ORDER BY started_at DESC, run_id DESC LIMIT 1",
                    (record["release"], record["sha256sums_sha256"], Jsonb(record.get("skipped", [])),
                     record.get("facts")))
        previous = cur.fetchone()
        cur.execute("INSERT INTO runs (run_id, release, started_at, finished_at, status, record) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (record["run_id"], record["release"], record["started_at"], record["finished_at"],
                     record["status"], Jsonb(record)))
    if previous is None or record["status"] != "succeeded":
        return None
    # Compared as JSON, as stored: a tuple in the counts reads back as a list.
    return {"run_id": previous[0], "same_counts": previous[1] == json.loads(json.dumps(record["counts"]))}


def number(name: str) -> int:
    """A step's number in backend design §6, whatever was skipped."""
    return [n for n, _ in STEPS].index(name) + 1


def run_steps(run: Run, steps: list[tuple[str, Callable[[Run], dict]]]) -> tuple[dict, dict, str | None, str | None]:
    """Call the steps in order until one fails. Returns counts and seconds per step, and the failed step and why."""
    counts, seconds = {}, {}
    for name, step in steps:
        started = time.perf_counter()
        try:
            counts[name] = step(run)
        except StepFailed as failure:
            return counts, seconds, name, str(failure)
        except (Exception, SystemExit) as failure:   # a store that cannot be reached, a missing file
            return counts, seconds, name, f"{type(failure).__name__}: {failure}"
        finally:
            seconds[name] = round(time.perf_counter() - started, 2)
        print(f"step {number(name)} {name}: ok in {seconds[name]:.1f} s; "
              + ", ".join(f"{k} {v}" for k, v in counts[name].items()))
    return counts, seconds, None, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("release", type=Path, help="K1 release folder (the one holding manifest.json)")
    parser.add_argument("--skip-vectors", action="store_true", help="skip step 3, which needs the embedding server")
    parser.add_argument("--skip-graphs", action="store_true", help="skip steps 4 to 7, the two Neo4j regions")
    parser.add_argument("--reload", action="store_true",
                        help="step 2: replace the release even when the store holds it unchanged (drops its vectors)")
    parser.add_argument("--replaces", metavar="RELEASE",
                        help="step 2: first remove this other release, which holds the same files (and its vectors)")
    parser.add_argument("--facts", choices=["mapped", "recorded", "tables"],
                        help="step 6: the recorded E27 fact graph moved onto the release's chunk IDs (the default when "
                             "the release holds a legacy map), as it is (the default otherwise), or one built from "
                             "the release's tables")
    parser.add_argument("--appendices", type=Path, default=event_graph.OLD_EXPORT,
                        help="corpus export holding appendix 23, when the release does not")
    parser.add_argument("--endpoint", default="local-embed", help="embedding endpoint in configs/graphrag/endpoints.json")
    parser.add_argument("--out", type=Path, default=OUT, help="the run writes its files under <out>/<run_id>/")
    args = parser.parse_args(argv)

    started = datetime.now(timezone.utc)
    name = args.release.resolve().name
    run_id = f"{name}-{started:%Y%m%dT%H%M%SZ}"
    facts = args.facts or default_facts(args.release)
    run = Run(args.release, name, args.out / run_id, appendices=args.appendices, facts=facts,
              endpoint=args.endpoint, reload=args.reload, replaces=args.replaces)
    run.out.mkdir(parents=True, exist_ok=True)
    skipped = (["embed"] if args.skip_vectors else []) + (sorted(GRAPH_STEPS) if args.skip_graphs else [])
    steps = [(n, s) for n, s in STEPS if n not in skipped]
    print(f"run {run_id}: {len(steps) + 1} steps" + (f", skipping {', '.join(skipped)}" if skipped else ""))

    counts, seconds, failed, reason = run_steps(run, steps)
    sums = run.release / SUMS
    record = {"run_id": run_id, "release": name, "release_folder": str(run.release),
              "sha256sums_sha256": hashlib.sha256(sums.read_bytes()).hexdigest() if sums.is_file() else None,
              "git_commit": git_commit(), "embedding_model": None if args.skip_vectors else run.embedding_model,
              "skipped": skipped, "facts": facts, "counts": counts, "seconds": seconds, "notes": run.notes,
              "started_at": started.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat(),
              "status": "failed" if failed else "succeeded", "failed_step": failed, "error": reason}
    if failed:
        print(f"step {number(failed)} {failed} failed: {reason}")
    try:
        previous = record_run(run.dsn, record)
    except Exception as failure:   # the run's outcome stands; only its record is lost
        print(f"step 8 record: failed, {type(failure).__name__}: {failure}")
        return 1
    print(f"step 8 record: run {run_id} written to runs ({record['status']})")
    if previous:
        print(f"counts {'equal' if previous['same_counts'] else 'DIFFER from'} those of the previous run of this "
              f"release, {previous['run_id']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
