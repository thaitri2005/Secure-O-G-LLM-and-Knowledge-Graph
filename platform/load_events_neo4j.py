"""Load Track B's event graph into Neo4j and check it (C-C11; Track B's note to Track C, need 3).

    python platform/load_events_neo4j.py                      # graphrag/results/E28_events.json, AK-3

The graph is the one E28 measured (161 events of AK-3's daily reports), as Track B recorded it. Nodes and
relationships:

    (:Well {name})-[:HAS_DAY]->(:ReportDay {day_id, well, date})-[:HAS_EVENT]->(:Event {event_id, seq, ...})
    (:Event)-[:HAS_CODE]->(:ActivityCode {code})
    (:Event)-[:NPT]->(:NptCode {code})                        only for non-productive events
    (:Event)-[:FROM {rank}]->(:Chunk {chunk_id, id_format})   the passages the event was read from

A `Chunk` node holds only the chunk ID; text and page stay in PostgreSQL (D-06: Neo4j is derived). `Event.seq`
keeps the recorded order, which the plan runner relies on (first and last dates). The recorded events cite the
chunk IDs of the corpus export E28 read, not K1 version 1 IDs, so `id_format` says which scheme an ID follows.

All in one write transaction, which rolls back if any check fails:
1. replace the well's days and events;
2. read the events back in order and compare them with the file, field by field;
3. replay every recorded query plan of E28 (`graphrag.events.run_plan`) on the events read back and compare with
   the result recorded in the run, with no model call;
4. compute hours per activity code and the non-productive totals in Cypher and compare with Python.
Needs `neo4j==6.4.1` (Track B's lock file), and numpy and httpx for `graphrag`.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from neo4j import GraphDatabase  # noqa: E402

from graphrag.events import Event, run_plan  # noqa: E402

URI, USER, PASSWORD = "bolt://127.0.0.1:7687", "neo4j", "platform-dev"   # platform/docker-compose.yml
EVENTS = ROOT / "graphrag/results/E28_events.json"
RUNS = [ROOT / "graphrag/results/E28_graph_fixed_seen.json", ROOT / "graphrag/results/E28_heldout_graph.json"]

CONSTRAINTS = [("Well", "name"), ("ReportDay", "day_id"), ("Event", "event_id"), ("ActivityCode", "code"),
               ("NptCode", "code"), ("Chunk", "chunk_id")]

CLEAR = """
MATCH (:Well {name: $well})-[:HAS_DAY]->(d:ReportDay)
OPTIONAL MATCH (d)-[:HAS_EVENT]->(e:Event)
DETACH DELETE d, e
WITH count(*) AS removed
MATCH (n) WHERE (n:Chunk OR n:ActivityCode OR n:NptCode) AND NOT (n)--()
DELETE n
"""

LOAD = """
MERGE (w:Well {name: $well})
WITH w
UNWIND $events AS ev
MERGE (d:ReportDay {day_id: $well + ':' + ev.date})
  ON CREATE SET d.well = $well, d.date = ev.date
MERGE (w)-[:HAS_DAY]->(d)
CREATE (e:Event {event_id: ev.event_id, seq: ev.seq, start_time: ev.start_time, end_time: ev.end_time,
                 hours: ev.hours, end_md: ev.end_md, description: ev.description})
CREATE (d)-[:HAS_EVENT]->(e)
MERGE (c:ActivityCode {code: ev.code})
CREATE (e)-[:HAS_CODE]->(c)
FOREACH (npt IN CASE WHEN ev.npt_code IS NULL THEN [] ELSE [ev.npt_code] END |
  MERGE (n:NptCode {code: npt})
  CREATE (e)-[:NPT]->(n))
FOREACH (i IN range(0, size(ev.chunks) - 1) |
  MERGE (ch:Chunk {chunk_id: ev.chunks[i]})
    ON CREATE SET ch.id_format = CASE WHEN ev.chunks[i] CONTAINS '#' THEN 'corpus export (K1 version 0 style)'
                                      ELSE 'K1 version 1' END
  CREATE (e)-[:FROM {rank: i}]->(ch))
"""

READ_BACK = """
MATCH (:Well {name: $well})-[:HAS_DAY]->(d:ReportDay)-[:HAS_EVENT]->(e:Event)-[:HAS_CODE]->(c:ActivityCode)
OPTIONAL MATCH (e)-[:NPT]->(n:NptCode)
OPTIONAL MATCH (e)-[f:FROM]->(ch:Chunk)
WITH d, e, c, n, f, ch ORDER BY e.seq, f.rank
WITH d, e, c, n, collect(ch.chunk_id) AS chunks
RETURN d.date AS date, e.start_time AS start_time, e.end_time AS end_time, e.hours AS hours, e.end_md AS end_md,
       c.code AS code, e.description AS description, chunks, n.code AS npt_code
ORDER BY e.seq
"""

HOURS_BY_CODE = """
MATCH (:Well {name: $well})-[:HAS_DAY]->(:ReportDay)-[:HAS_EVENT]->(e:Event)-[:HAS_CODE]->(c:ActivityCode)
RETURN c.code AS code, sum(e.hours) AS hours
"""

NON_PRODUCTIVE = """
MATCH (:Well {name: $well})-[:HAS_DAY]->(d:ReportDay)-[:HAS_EVENT]->(e:Event)-[:NPT]->(:NptCode)
RETURN sum(e.hours) AS hours, count(e) AS events, count(DISTINCT d) AS days
"""


class CheckFailed(Exception):
    """Raised inside the transaction so that a failed check rolls the load back."""


def parameters(events: list[Event], well: str) -> list[dict]:
    return [{"event_id": f"{well}:{n}", "seq": n, "date": e.date, "start_time": e.start, "end_time": e.end,
             "hours": float(e.hours), "end_md": e.end_md, "description": e.description, "code": e.code,
             "npt_code": e.npt_code, "chunks": e.chunks} for n, e in enumerate(events)]


def recorded_plans(runs: list[Path]) -> list[tuple[str, dict, str]]:
    plans = []
    for path in runs:
        for row in json.loads(path.read_text(encoding="utf-8"))["rows"]:
            if row.get("plan"):
                plans.append((f"{path.stem}/{row['id']}", row["plan"], row.get("graph_result") or ""))
    return plans


def python_totals(events: list[Event]) -> tuple[dict[str, float], tuple[float, int, int]]:
    by_code: Counter = Counter()
    for e in events:
        by_code[e.code] += e.hours
    npt = [e for e in events if e.npt_code is not None]
    return dict(by_code), (sum(e.hours for e in npt), len(npt), len({e.date for e in npt}))


def load_and_check(tx, events: list[Event], well: str, plans: list[tuple[str, dict, str]]) -> dict:
    tx.run(CLEAR, well=well).consume()
    tx.run(LOAD, well=well, events=parameters(events, well)).consume()

    back = [Event(date=r["date"], start=r["start_time"], end=r["end_time"], hours=r["hours"], end_md=r["end_md"],
                  code=r["code"], description=r["description"], chunks=list(r["chunks"]), npt_code=r["npt_code"])
            for r in tx.run(READ_BACK, well=well)]
    same = sum(a == b for a, b in zip(back, events))
    problems = [f"event {n}: {asdict(b)} read back as {asdict(a)}" for n, (a, b) in enumerate(zip(back, events)) if a != b]
    if len(back) != len(events):
        problems.append(f"{len(back)} events read back, {len(events)} in the file")

    replayed = [(name, run_plan(plan, back, well)[0], recorded) for name, plan, recorded in plans]
    problems += [f"plan {name}: {got!r} != recorded {want!r}" for name, got, want in replayed if got != want]

    by_code, (npt_hours, npt_events, npt_days) = python_totals(events)
    cypher_by_code = {r["code"]: r["hours"] for r in tx.run(HOURS_BY_CODE, well=well)}
    npt = tx.run(NON_PRODUCTIVE, well=well).single()
    code_matches = sum(abs(cypher_by_code.get(code, -1) - hours) < 1e-9 for code, hours in by_code.items())
    if code_matches != len(by_code) or set(cypher_by_code) != set(by_code):
        problems.append(f"hours by code: Cypher {cypher_by_code} != Python {by_code}")
    if (abs(npt["hours"] - npt_hours) > 1e-9, npt["events"], npt["days"]) != (False, npt_events, npt_days):
        problems.append(f"non-productive totals: Cypher {dict(npt)} != Python {(npt_hours, npt_events, npt_days)}")

    counts = tx.run("MATCH (:Well {name: $well})-[:HAS_DAY]->(d:ReportDay)-[:HAS_EVENT]->(e:Event) "
                    "OPTIONAL MATCH (e)-[:FROM]->(ch:Chunk) "
                    "RETURN count(DISTINCT d) AS days, count(DISTINCT e) AS events, count(DISTINCT ch) AS chunks",
                    well=well).single().data()
    summary = {"events_same": same, "events": len(events), "plans_same": sum(g == w for _, g, w in replayed),
               "plans": len(plans), "codes_same": code_matches, "codes": len(by_code),
               "npt": (npt_hours, npt_events, npt_days), **counts}
    if problems:
        raise CheckFailed("\n  ".join([f"{len(problems)} problems, load rolled back:"] + problems[:10]))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--events", type=Path, default=EVENTS)
    parser.add_argument("--uri", default=URI)
    parser.add_argument("--user", default=USER)
    parser.add_argument("--password", default=PASSWORD)
    args = parser.parse_args(argv)

    recorded = json.loads(args.events.read_text(encoding="utf-8"))
    (well,) = recorded["wells"]
    events = [Event(**e) for e in recorded["events"]]
    plans = recorded_plans(RUNS)
    with GraphDatabase.driver(args.uri, auth=(args.user, args.password)) as driver:
        driver.verify_connectivity()
        for label, key in CONSTRAINTS:
            driver.execute_query(f"CREATE CONSTRAINT {label.lower()}_{key} IF NOT EXISTS "
                                 f"FOR (n:{label}) REQUIRE n.{key} IS UNIQUE")
        with driver.session() as session:
            try:
                s = session.execute_write(load_and_check, events, well, plans)
            except CheckFailed as failure:
                print(failure)
                return 1
    print(f"loaded {well}: {s['days']} report days, {s['events']} events, {s['chunks']} source chunks")
    print(f"read back: {s['events_same']} / {s['events']} events identical to {args.events.name}")
    print(f"replayed: {s['plans_same']} / {s['plans']} recorded query plans give the recorded result")
    print(f"Cypher: hours for {s['codes_same']} / {s['codes']} activity codes match Python; non-productive "
          f"{s['npt'][0]:g} hours in {s['npt'][1]} events on {s['npt'][2]} days")
    return 0


if __name__ == "__main__":
    sys.exit(main())
