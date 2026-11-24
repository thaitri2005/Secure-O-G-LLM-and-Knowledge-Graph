"""The engine read from the stores (graphrag/stores.py) equals the engine read from files, on the same data.

Unit tests need no service. Integration tests skip when the local PostgreSQL or Neo4j does not answer
(docs/tracks/B-graphrag/plan-production-readiness.md). Both stores are shared with other agents, so these tests write
only where nobody else reads: PostgreSQL tables in a temporary schema, dropped afterwards, and Neo4j nodes under
test-only keys (wells `WTWO-<n>`, every chunk, document and code prefixed `wtwo-`), deleted afterwards.

With `GRAPHRAG_K1_CHUNKS` pointing at a real K1 package (graphrag/data.py), one more test loads that package.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graphrag import baseline, lanes, stores  # noqa: E402
from graphrag.data import load_chunks  # noqa: E402
from graphrag.events import Event  # noqa: E402
from graphrag.factgraph import to_graph  # noqa: E402
from graphrag.retrieval import well_names  # noqa: E402
from graphrag.validate import validate  # noqa: E402

DSN = "postgresql://kg:platform-dev@127.0.0.1:5434/kg"   # the local stores (platform/docker-compose.yml)
NEO4J = ("bolt://127.0.0.1:7687", "neo4j", "platform-dev")
PREFIX, WELL = "wtwo-", "WTWO-9"
RELEASE = "wtwo-sample"
SQL = [ROOT / "platform/sql/001_k1.sql", ROOT / "platform/sql/002_questions.sql"]
EVENTS_FILE = ROOT / "graphrag/results/E31_events_k1.json"
FACT_RUNS = ["E20_graph_three_qwen3-4b", "E27_tables_three"]   # the runs E27_fact_graph.graph.json was built from
KEYS = {"Well": "name", "Chunk": "chunk_id", "Document": "file_id", "Fact": "fact_id", "CasingString": "casing_id",
        "HoleSection": "section_id"}   # backend design §4.1
CLEANUP = """
MATCH (n) WHERE (n:Well AND n.name STARTS WITH 'WTWO-') OR (n:Fact AND n.fact_id STARTS WITH 'WTWO-')
   OR (n:CasingString AND n.casing_id STARTS WITH 'WTWO-') OR (n:HoleSection AND n.section_id STARTS WITH 'WTWO-')
   OR (n:ReportDay AND n.day_id STARTS WITH 'WTWO-') OR (n:Event AND n.event_id STARTS WITH 'WTWO-')
   OR (n:Chunk AND n.chunk_id STARTS WITH $prefix) OR (n:Document AND n.file_id STARTS WITH $prefix)
   OR (n:ActivityCode AND n.code STARTS WITH $prefix) OR (n:NptCode AND n.code STARTS WITH $prefix)
DETACH DELETE n
"""


def platform_module(name: str):
    """A script of platform/, which is a folder of scripts and not a package (C-C02)."""
    spec = importlib.util.spec_from_file_location(f"platform_{name}", ROOT / f"platform/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---- data ----------------------------------------------------------------------------------------------------------

EOW, DAILY = "f" + "e" * 16, "f" + "d" * 16
EOW_DOC, DAILY_DOC = "gdr882_ak3_eowr", "wtwo-appx-30-6-dailyreportsummaryrpt-0a1b2c3d"


def chunk_record(chunk_id: str, doc_id: str, page: int, text: str, kind: str = "text", table_id: str | None = None,
                 rows: tuple[int, int] | None = None, context: dict | None = None) -> dict:
    parent = chunk_id.rsplit(":", 1)[0]
    return {"chunk_id": chunk_id, "parent_id": parent, "file_id": chunk_id.split(":")[0], "doc_id": doc_id,
            "table_id": table_id, "form_id": None, "type": kind, "child_index": int(chunk_id.rsplit(":c", 1)[1]),
            "page": page, "pages": [page], "text": text, "sha256": uuid.uuid5(uuid.NAMESPACE_URL, chunk_id).hex * 2,
            "quality": "ok", "context": context or {}, "section": "Summary" if kind == "text" else None,
            "row_start": rows and rows[0], "row_end": rows and rows[1]}


def sample_package() -> dict:
    """A tiny K1 version 1 release, one end-of-well report and one daily report, in the shape platform/load_k1.py
    loads. Its daily report is named as Track A names them, so `is_daily` and `baseline.pool` tell the two apart."""
    chunks = [
        chunk_record(f"{EOW}:s1:c0", EOW_DOC, 1, "Well AK-3 reached a total depth of 1,955 ft on 30 August 2016."),
        chunk_record(f"{EOW}:s1:c1", EOW_DOC, 2, "The 8-5/8 in casing was set at 40 ft."),
        chunk_record(f"{DAILY}:s1:c0", DAILY_DOC, 1, "Report For 20-Aug-16 Well ID: AK-3",
                     context={"report_date": "20-Aug-16", "well": "AK-3"}),
        chunk_record(f"{DAILY}:t1:c0", DAILY_DOC, 1, "| 0:00 | 9:30 | 9.5 | 100 | DRIL | drilling ahead |", "table",
                     f"{DAILY}:t1", (1, 1), {"report_date": "20-Aug-16", "well": "AK-3"}),
    ]
    files = [{"file_id": f, "doc_id": d, "document_type": t, "sha256": f[1:] + "0" * 48, "page_count": 2}
             for f, d, t in ((EOW, EOW_DOC, "eowr"), (DAILY, DAILY_DOC, "daily_report"))]
    parents = [{"parent_id": p, "file_id": p.split(":")[0], "type": "table" if ":t" in p else "section", "pages": [1, 2],
                "document_type": "eowr" if p.startswith(EOW) else "daily_report"}
               for p in (f"{EOW}:s1", f"{DAILY}:s1", f"{DAILY}:t1")]
    tables = [{"table_id": f"{DAILY}:t1", "file_id": DAILY, "logical_id": "t1", "pages": [1], "num_rows": 2, "num_cols": 6}]
    return {"manifest": {"schema_version": "test"}, "sums_sha256": "0" * 64, "files": files, "pages": [],
            "parents": parents, "tables": tables, "forms": [], "chunks": chunks, "legacy": []}


def write_chunks(records: list[dict], folder: str) -> Path:
    path = Path(folder, "chunks.jsonl")
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def sample_events() -> list[Event]:
    """E31's 161 events (the event graph on K1 version 1), with their chunk IDs and codes under the test prefix."""
    events = [Event(**e) for e in json.loads(EVENTS_FILE.read_text(encoding="utf-8"))["events"]]
    return [Event(e.date, e.start, e.end, e.hours, e.end_md, PREFIX + e.code, e.description,
                  [PREFIX + c for c in e.chunks], e.npt_code and PREFIX + e.npt_code) for e in events]


def sample_facts() -> list[dict]:
    """The validated facts the fact graph is built from (graphrag.factgraph), each well renamed WTWO-<n> and each
    chunk put under the test prefix. Facts not naming exactly one well are left out, as `to_graph` leaves them out."""
    raw = [f for name in FACT_RUNS for f in json.loads((baseline.RESULTS / f"{name}.json").read_text(encoding="utf-8"))["facts"]]
    kept, _ = validate(raw, {c.id: c.text for c in baseline.pool("three")}, strict=True)
    named = [(f, well_names(str(f.get("well") or ""))) for f in kept]
    renamed = {w: f"WTWO-{n + 1}" for n, w in enumerate(sorted({w for _, ws in named if len(ws) == 1 for w in ws}))}
    return [dict(f, well=renamed[next(iter(ws))], chunk=PREFIX + f["chunk"]) for f, ws in named if len(ws) == 1]


# ---- the stores ----------------------------------------------------------------------------------------------------

def postgres_reason() -> str | None:
    try:
        import psycopg
        with psycopg.connect(DSN, connect_timeout=3):
            return None
    except Exception as error:  # noqa: BLE001 - any failure means: skip
        return f"no local PostgreSQL at {DSN} ({type(error).__name__})"


def neo4j_reason() -> str | None:
    try:
        from neo4j import GraphDatabase
        with GraphDatabase.driver(NEO4J[0], auth=NEO4J[1:], connection_timeout=3) as driver:
            driver.verify_connectivity()
            return None
    except Exception as error:  # noqa: BLE001
        return f"no local Neo4j at {NEO4J[0]} ({type(error).__name__})"


NO_POSTGRES, NO_NEO4J = postgres_reason(), neo4j_reason()


@contextlib.contextmanager
def temporary_schema(package: dict | None = None, release: str = RELEASE):
    """A schema of its own with the tables of platform/sql/, optionally one K1 release loaded by platform/load_k1.py;
    yields a DSN whose search path is that schema. Dropped at the end."""
    import psycopg
    schema = f"w2_test_{uuid.uuid4().hex[:10]}"
    dsn = f"{DSN}?options=-csearch_path%3D{schema},public"
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(f"CREATE SCHEMA {schema}")
    try:
        with psycopg.connect(dsn) as conn:
            for path in SQL:
                conn.execute(path.read_text(encoding="utf-8"))
            if package is not None:
                with conn.cursor() as cur:
                    platform_module("load_k1").load(cur, release, package)
        yield dsn
    finally:
        with psycopg.connect(DSN, autocommit=True) as conn:
            conn.execute(f"DROP SCHEMA {schema} CASCADE")


def load_fact_graph(driver, graph: dict) -> None:
    """The fact region as backend design §4.1 loads it: MERGE each node on its key, then each relationship."""
    for label, key in KEYS.items():
        nodes = [{"key": n["key"], "properties": n["properties"]} for n in graph["nodes"] if n["label"] == label]
        driver.execute_query(f"UNWIND $nodes AS n MERGE (x:{label} {{{key}: n.key}}) SET x += n.properties", nodes=nodes)
    groups: dict[tuple[str, str, str], list] = {}
    for r in graph["relationships"]:
        groups.setdefault((r["type"], r["from"][0], r["to"][0]), []).append({"from": r["from"][1], "to": r["to"][1]})
    for (kind, start, end), rels in groups.items():
        driver.execute_query(f"UNWIND $rels AS r MATCH (a:{start} {{{KEYS[start]}: r.from}}), (b:{end} {{{KEYS[end]}: r.to}}) "
                             f"MERGE (a)-[:{kind}]->(b)", rels=rels)


def load_events(driver, events: list[Event], well: str = WELL) -> None:
    """The event region exactly as platform/load_events_neo4j.py writes it."""
    loader = platform_module("load_events_neo4j")
    driver.execute_query(loader.LOAD, well=well, events=loader.parameters(events, well))


# ---- unit tests ----------------------------------------------------------------------------------------------------

class FakeDriver:
    """Answers the two Cypher reads of graphrag.stores from a fact graph and a list of events, as Neo4j would."""

    def __init__(self, graph: dict | None = None, events: list[Event] | None = None):
        self.graph, self.events = graph or {"nodes": [], "relationships": []}, events or []

    def execute_query(self, query, **params):
        if query == stores.EVENTS:
            rows = [{"date": e.date, "start_time": e.start, "end_time": e.end, "hours": e.hours, "end_md": e.end_md,
                     "code": e.code, "description": e.description, "chunks": e.chunks, "npt_code": e.npt_code}
                    for e in self.events]
            return SimpleNamespace(records=rows)
        props = {(n["label"], n["key"]): n["properties"] for n in self.graph["nodes"]}
        rels = self.graph["relationships"]
        wells = {r["to"][1]: r["from"][1] for r in rels if r["type"] == "HAS_FACT"}
        rows = []
        for r in sorted((r for r in rels if r["type"] == "FROM"), key=lambda r: (r["from"][1], r["to"][1])):
            if params["well"] is None or wells[r["from"][1]] == params["well"]:
                rows.append({"well": wells[r["from"][1]], "fact": props[("Fact", r["from"][1])], "chunk": r["to"][1]})
        return SimpleNamespace(records=rows)


class StoreReaderTests(unittest.TestCase):
    def test_store_records_become_the_same_chunks_as_the_file(self):
        records = sample_package()["chunks"]
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(stores.to_chunks(records), load_chunks(path=write_chunks(records, folder)))

    def test_daily_reports_and_the_non_productive_report_are_daily(self):
        self.assertTrue(stores.is_daily(DAILY_DOC))
        self.assertTrue(stores.is_daily("gdr882-ak3-appx-23-6-nptreport-0a1b2c3d"))
        self.assertFalse(stores.is_daily(EOW_DOC))

    def test_read_facts_gives_back_the_graph_they_were_loaded_from(self):
        facts = [
            {"chunk": "d#c0013", "well": "Well AK-3", "property": "casing_depth", "qualifier": "actual",
             "context": {"casing_size_in": "8-5/8"}, "value": 40, "source": "d#t003"},
            {"chunk": "d#c0037", "well": "AK-3", "property": "non_productive_time", "qualifier": "actual",
             "context": None, "value": "115.0", "unit": "hours"},
            {"chunk": "d#c0038", "well": "AK-3", "property": "non_productive_time", "qualifier": "actual",
             "context": {}, "value": "115.0", "unit": "hours"},   # the same fact from a second chunk
        ]
        graph = to_graph(facts)
        back = stores.read_facts(FakeDriver(graph))
        self.assertEqual(to_graph(back), graph)
        self.assertEqual(back[0], {"well": "AK-3", "property": "casing_depth", "value": "40", "qualifier": "actual",
                                   "context": {"casing_size_in": "8-5/8"}, "chunk": "d#c0013", "source": "table_mapping"})
        self.assertEqual((back[1]["context"], back[1]["source"], back[1]["unit"]), (None, None, "hours"))

    def test_read_events_gives_the_events_field_by_field(self):
        events = sample_events()[:20]
        self.assertEqual(stores.read_events(FakeDriver(events=events), WELL), events)

    def test_importing_the_readers_needs_neither_database_driver(self):
        out = subprocess.run([sys.executable, "-c", "import sys, graphrag.stores; "
                              "print('psycopg' in sys.modules, 'neo4j' in sys.modules)"],
                             capture_output=True, text=True, cwd=ROOT, env={**os.environ, "OPENBLAS_NUM_THREADS": "1"})
        self.assertEqual((out.returncode, out.stdout.split()), (0, ["False", "False"]), out.stderr[-2000:])

    def test_the_events_query_is_the_event_loaders_read_back(self):
        try:
            loader = platform_module("load_events_neo4j")
        except ImportError as missing:
            self.skipTest(f"platform/load_events_neo4j.py needs {missing.name}")
        self.assertEqual(" ".join(stores.EVENTS.split()), " ".join(loader.READ_BACK.split()))

    def test_an_unreachable_postgresql_raises_instead_of_giving_an_empty_engine(self):
        try:
            import psycopg
        except ImportError:
            self.skipTest("needs psycopg")
        with self.assertRaises(psycopg.OperationalError):
            stores.engine_from_stores("postgresql://kg:x@127.0.0.1:1/kg?connect_timeout=2", *NEO4J)


# ---- integration tests ---------------------------------------------------------------------------------------------

@unittest.skipIf(NO_POSTGRES, NO_POSTGRES or "")
class PostgresChunkTests(unittest.TestCase):
    def test_read_chunks_gives_the_package_records_in_order(self):
        package = sample_package()
        with temporary_schema(package) as dsn:
            self.assertEqual(stores.read_chunks(dsn, RELEASE), package["chunks"])
            self.assertEqual(stores.read_chunks(dsn), package["chunks"])   # the only release
            with self.assertRaisesRegex(LookupError, "not in the store"):
                stores.read_chunks(dsn, "no-such-release")
        with temporary_schema() as dsn, self.assertRaisesRegex(LookupError, "holds none"):
            stores.read_chunks(dsn)

    @unittest.skipUnless(os.environ.get("GRAPHRAG_K1_CHUNKS"), "set GRAPHRAG_K1_CHUNKS to a K1 package's chunks.jsonl")
    def test_a_real_k1_package_reads_back_as_the_files_give_it(self):
        loader = platform_module("load_k1")
        folder = Path(os.environ["GRAPHRAG_K1_CHUNKS"]).parent
        package = loader.read_package(folder)
        with temporary_schema(package, folder.name) as dsn:
            with contextlib.redirect_stdout(io.StringIO()):
                import psycopg
                with psycopg.connect(dsn) as conn, conn.cursor() as cur:
                    self.assertEqual(loader.check(cur, folder.name, package), [])
            records = stores.read_chunks(dsn, folder.name)
        self.assertEqual(records, package["chunks"])
        chunks = stores.to_chunks(records)
        self.assertEqual([c for c in chunks if not stores.is_daily(c.doc_id)], baseline.pool("k1_ak3"))
        self.assertEqual([c for c in chunks if stores.is_daily(c.doc_id)], baseline.pool("k1_daily"))


@unittest.skipIf(NO_NEO4J, NO_NEO4J or "")
class Neo4jReaderTests(unittest.TestCase):
    def setUp(self):
        from neo4j import GraphDatabase
        self.driver = GraphDatabase.driver(NEO4J[0], auth=NEO4J[1:])
        self.addCleanup(self.driver.close)
        self.driver.execute_query(CLEANUP, prefix=PREFIX)
        self.addCleanup(self.driver.execute_query, CLEANUP, prefix=PREFIX)

    def test_events_read_back_equal_the_events_loaded(self):
        events = sample_events()
        load_events(self.driver, events)
        self.assertEqual(stores.read_events(self.driver, WELL), events)
        self.assertEqual(stores.read_events(self.driver, "WTWO-404"), [])

    def test_facts_read_back_give_the_loaded_fact_graph(self):
        graph = to_graph(sample_facts())
        load_fact_graph(self.driver, graph)
        # Other agents may have loaded the real fact region into the same database: only the test wells count.
        back = [f for f in stores.read_facts(self.driver) if f["well"].startswith("WTWO-")]
        self.assertEqual(to_graph(back), graph)
        self.assertGreater(len(back), 100)
        one = stores.read_facts(self.driver, "WTWO-1")
        self.assertEqual({f["well"] for f in one}, {"WTWO-1"})
        self.assertEqual(len(one), sum(r["type"] == "FROM" and r["from"][1].startswith("WTWO-1|")
                                       for r in graph["relationships"]))


@unittest.skipIf(NO_POSTGRES or NO_NEO4J, NO_POSTGRES or NO_NEO4J or "")
class EngineFromStoresTests(unittest.TestCase):
    def setUp(self):
        from neo4j import GraphDatabase
        self.driver = GraphDatabase.driver(NEO4J[0], auth=NEO4J[1:])
        self.addCleanup(self.driver.close)
        self.driver.execute_query(CLEANUP, prefix=PREFIX)
        self.addCleanup(self.driver.execute_query, CLEANUP, prefix=PREFIX)

    def test_the_engine_from_the_stores_equals_the_engine_from_files(self):
        package, events, facts = sample_package(), sample_events(), sample_facts()
        load_events(self.driver, events)
        load_fact_graph(self.driver, to_graph(facts))
        with temporary_schema(package) as dsn, self.assertLogs("graphrag.stores", "WARNING") as logged:
            engine = stores.engine_from_stores(dsn, *NEO4J, release=RELEASE, well=WELL, multi_well_retriever="perwell:bm25")
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.dict(os.environ, {"GRAPHRAG_K1_CHUNKS": str(write_chunks(package["chunks"], folder))}):
            eow, daily = baseline.pool("k1_ak3"), baseline.pool("k1_daily")
        self.assertEqual((engine.eow_chunks, engine.daily_chunks), (eow, daily))
        self.assertEqual(engine.events, events)
        self.assertEqual(to_graph([f for f in engine.facts if f["well"].startswith("WTWO-")]), to_graph(facts))
        self.assertEqual((engine.multi_well_retriever, getattr(engine, "source")), ("perwell:bm25", "stores"))
        # The test events and facts cite chunks this release does not hold: said by count, not hidden.
        self.assertTrue(any("cited by events" in line for line in logged.output))
        self.assertTrue(any("cited by facts" in line for line in logged.output))
        # The lanes run on it as on a file-loaded engine.
        hits = lanes.passages("What total depth did AK-3 reach?", {"report_type": "end_of_well"}, engine)
        self.assertEqual(hits.passages[0], f"{EOW}:s1:c0")
        self.assertTrue(lanes.well_facts("What casing was set in WTWO-1?", {}, engine).facts)

    def test_an_unreachable_neo4j_raises(self):
        from neo4j.exceptions import ServiceUnavailable
        with temporary_schema(sample_package()) as dsn, self.assertRaises(ServiceUnavailable):
            stores.engine_from_stores(dsn, "bolt://127.0.0.1:1", "neo4j", "x")


if __name__ == "__main__":
    unittest.main()
