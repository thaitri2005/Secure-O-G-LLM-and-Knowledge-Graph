"""The two Neo4j loaders (backend design §4): file checks and settings without services, then real loads of a
test-only well that skip when Neo4j cannot be reached. The tests never clear the real AK-3 data: they load their
own well name and remove only what they created."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "platform"))

import load_events_neo4j as events_loader  # noqa: E402
import load_facts_neo4j as facts_loader  # noqa: E402

UNREACHABLE_DSN = "postgresql://kg:x@127.0.0.1:1/kg"
REAL_WELLS = ["56-32", "68-32", "AK-3", "TG-2", "TG-4"]   # the event region's well and the fact graph's


def small_graph(well: str, value: str = "1955") -> dict:
    """A fact graph in graphrag.factgraph's shape, for one test well, with one fact, one casing string and one hole
    section; one chunk ID in each ID format."""
    doc, old_chunk, new_chunk = f"{well}-doc", f"{well}-doc#c0001", "f0000000000000000:s1:c0"
    fact = f"{well}|casing_depth|actual|{{\"casing_size_in\": \"8-5/8\"}}|{value}"
    other = f"{well}|hole_size|actual|{{}}|12-1/4"
    nodes = [("Well", well, {"name": well}), ("Document", doc, {"doc_id": doc}), ("Chunk", old_chunk, {}),
             ("Chunk", new_chunk, {}),
             ("Fact", fact, {"property": "casing_depth", "value": value, "qualifier": "actual",
                             "context": "{\"casing_size_in\": \"8-5/8\"}", "source": "table_mapping", "unit": "ft"}),
             ("Fact", other, {"property": "hole_size", "value": "12-1/4", "qualifier": "actual", "context": "{}",
                              "source": "llm"}),
             ("CasingString", f"{well}|8-5/8", {"casing_size_in": "8-5/8", "depth": value}),
             ("HoleSection", f"{well}|12-1/4", {"hole_size_in": "12-1/4"})]
    rels = [("HAS_FACT", ("Well", well), ("Fact", fact)), ("HAS_FACT", ("Well", well), ("Fact", other)),
            ("FROM", ("Fact", fact), ("Chunk", old_chunk)), ("FROM", ("Fact", other), ("Chunk", new_chunk)),
            ("DESCRIBED_BY", ("Well", well), ("Document", doc)), ("HAS_CHUNK", ("Document", doc), ("Chunk", old_chunk)),
            ("HAS_CHUNK", ("Document", doc), ("Chunk", new_chunk)),
            ("HAS_CASING", ("Well", well), ("CasingString", f"{well}|8-5/8")),
            ("HAS_SECTION", ("Well", well), ("HoleSection", f"{well}|12-1/4"))]
    return {"nodes": [{"label": l, "key": k, "properties": p} for l, k, p in nodes],
            "relationships": [{"type": t, "from": list(a), "to": list(b), "properties": {}} for t, a, b in rels]}


class FactFileTests(unittest.TestCase):
    def test_the_committed_fact_graph_passes_the_file_checks(self):
        graph = json.loads(facts_loader.GRAPH.read_text(encoding="utf-8"))
        self.assertEqual(facts_loader.check_file(graph), [])
        self.assertEqual(facts_loader.file_wells(graph), ["56-32", "68-32", "AK-3", "TG-2", "TG-4"])

    def test_each_mistake_in_a_file_is_named(self):
        graph = small_graph("TEST-FILE")
        self.assertEqual(facts_loader.check_file(graph), [])
        broken = json.loads(json.dumps(graph))
        broken["relationships"].append({"type": "FROM", "from": ["Fact", "nowhere"], "to": ["Chunk", "nothing"]})
        broken["relationships"].append({"type": "HAS_FACT", "from": ["Document", "TEST-FILE-doc"],
                                        "to": ["Fact", graph["nodes"][4]["key"]]})
        broken["nodes"].append({"label": "Rig", "key": "R-1", "properties": {}})
        broken["nodes"].append(graph["nodes"][0])
        problems = "\n".join(facts_loader.check_file(broken))
        self.assertIn("dangling", problems)
        self.assertIn("HAS_FACT from Document to Fact is not in the fact region's design", problems)
        self.assertIn("unknown label Rig", problems)
        self.assertIn("appears 2 times", problems)

    def test_a_bad_file_is_refused_before_connecting(self):
        broken = small_graph("TEST-FILE")
        broken["relationships"][0]["to"] = ["Fact", "missing"]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.graph.json"
            path.write_text(json.dumps(broken), encoding="utf-8")
            with mock.patch.object(facts_loader, "GraphDatabase") as driver:
                with self.assertRaisesRegex(facts_loader.CheckFailed, "nothing loaded"):
                    facts_loader.load(path)
                driver.driver.assert_not_called()


class SettingsTests(unittest.TestCase):
    def test_connection_settings_come_from_the_environment(self):
        settings = {"NEO4J_URI": "bolt://elsewhere:7687", "NEO4J_USER": "u", "NEO4J_PASSWORD": "p",
                    "BACKEND_DSN": "postgresql://a@b/c"}
        # A separate copy of the module, so the one other tests use keeps its classes and settings.
        spec = importlib.util.spec_from_file_location("events_loader_copy", ROOT / "platform/load_events_neo4j.py")
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(os.environ, settings):
            spec.loader.exec_module(module)
        self.assertEqual((module.URI, module.USER, module.PASSWORD, module.DSN),
                         ("bolt://elsewhere:7687", "u", "p", "postgresql://a@b/c"))

    def test_event_loader_arguments(self):
        with mock.patch.object(events_loader, "load", side_effect=events_loader.CheckFailed("stop")) as load, \
                mock.patch("builtins.print"):
            self.assertEqual(events_loader.main([]), 1)
            self.assertEqual(load.call_args.args[:3], (events_loader.EVENTS, events_loader.RUNS, None))
            events_loader.main(["--events", "x.json", "--runs", "--well", "TEST-1"])
            self.assertEqual(load.call_args.args[:3], (Path("x.json"), [], "TEST-1"))
            events_loader.main(["--runs", "a.json", "b.json"])
            self.assertEqual(load.call_args.args[1], [Path("a.json"), Path("b.json")])

    def test_chunk_id_formats_and_an_unreachable_postgres(self):
        ids = {"gdr882_ak3_eowr#c0013", "f62efbee00767a3e7:s6:c0"}
        self.assertEqual(events_loader.k1_chunk_ids(ids), {"f62efbee00767a3e7:s6:c0"})
        self.assertEqual(events_loader.missing_in_postgres(set(), UNREACHABLE_DSN), 0)
        self.assertIsNone(events_loader.missing_in_postgres({"f62efbee00767a3e7:s6:c0"}, UNREACHABLE_DSN))


def neo4j_driver():
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(events_loader.URI, auth=(events_loader.USER, events_loader.PASSWORD),
                                  notifications_min_severity="OFF")
    try:
        driver.verify_connectivity()
    except Exception as error:  # noqa: BLE001 - any failure to connect means the service is not there
        driver.close()
        raise unittest.SkipTest(f"Neo4j not reachable at {events_loader.URI}: {error}")
    return driver


class Neo4jCase(unittest.TestCase):
    """Each test gets its own well name and removes that well's nodes afterwards."""

    def setUp(self):
        self.driver = neo4j_driver()
        self.addCleanup(self.driver.close)
        self.well = f"TEST-W1-{uuid.uuid4().hex[:8]}"
        self.addCleanup(self.remove_well)

    def remove_well(self):
        with self.driver.session() as session:
            session.execute_write(lambda tx: [tx.run(s, wells=[self.well]).consume() for s in facts_loader.CLEAR])
            session.execute_write(lambda tx: tx.run(events_loader.CLEAR, well=self.well).consume())
        self.driver.execute_query("MATCH (w:Well {name: $well}) DETACH DELETE w", well=self.well)

    def query(self, cypher: str, **parameters):
        return [r.data() for r in self.driver.execute_query(cypher, **parameters).records]

    def others(self) -> list[dict]:
        """What belongs to the real wells, which a test must leave as it found it. Other agents' test wells come
        and go on the shared database, so they are not looked at."""
        return self.query("MATCH (w:Well) WHERE w.name IN $real OPTIONAL MATCH (w)-[r]->() "
                          "RETURN w.name AS well, type(r) AS type, count(r) AS n ORDER BY well, type", real=REAL_WELLS)


class FactLoaderTests(Neo4jCase):
    def load(self, graph: dict) -> dict:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.graph.json"
            path.write_text(json.dumps(graph), encoding="utf-8")
            return facts_loader.load(path, dsn=UNREACHABLE_DSN, clear_wells=[self.well])

    def test_loads_checks_and_a_second_load_changes_nothing(self):
        before = self.others()
        first = self.load(small_graph(self.well))
        self.assertEqual(first["nodes"], {"CasingString": 1, "Chunk": 2, "Document": 1, "Fact": 2, "HoleSection": 1,
                                          "Well": 1})
        self.assertEqual(first["relationships"], {"DESCRIBED_BY": 1, "FROM": 2, "HAS_CASING": 1, "HAS_CHUNK": 2,
                                                  "HAS_FACT": 2, "HAS_SECTION": 1})
        self.assertEqual((first["facts_same"], first["facts"]), (2, 2))
        self.assertEqual((first["k1_chunks"], first["k1_chunks_missing_in_postgres"]), (1, None))
        second = self.load(small_graph(self.well))
        self.assertEqual({k: v for k, v in second.items()}, first)
        fact = self.query("MATCH (:Well {name: $well})-[:HAS_FACT]->(f:Fact {property: 'casing_depth'})-[:FROM]->(c) "
                          "RETURN f.value AS value, f.unit AS unit, f.context AS context, c.id_format AS format",
                          well=self.well)
        self.assertEqual(fact, [{"value": "1955", "unit": "ft", "context": "{\"casing_size_in\": \"8-5/8\"}",
                                 "format": "corpus export (K1 version 0 style)"}])
        self.assertEqual(self.others(), before)

    def test_a_failed_check_rolls_the_load_back(self):
        self.load(small_graph(self.well, "1955"))
        phantom = facts_loader.READ_RELATIONSHIPS + (
            "UNION RETURN 'HAS_FACT' AS type, 'Well' AS a_label, $wells[0] AS a_key, 'Fact' AS b_label, "
            "'phantom' AS b_key")
        with mock.patch.object(facts_loader, "READ_RELATIONSHIPS", phantom):
            with self.assertRaisesRegex(facts_loader.CheckFailed, "rolled back"):
                self.load(small_graph(self.well, "2000"))
        values = self.query("MATCH (:Well {name: $well})-[:HAS_CASING]->(c) RETURN c.depth AS depth", well=self.well)
        self.assertEqual(values, [{"depth": "1955"}])

    def test_the_event_region_is_left_alone(self):
        recorded = json.loads(events_loader.EVENTS.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.json"
            path.write_text(json.dumps({**recorded, "events": recorded["events"][:3]}), encoding="utf-8")
            events_loader.load(path, [], self.well, dsn=UNREACHABLE_DSN)
        days = self.query("MATCH (:Well {name: $well})-[:HAS_DAY]->(d)-[:HAS_EVENT]->(e) "
                          "RETURN count(DISTINCT d) AS days, count(e) AS events", well=self.well)
        self.load(small_graph(self.well))
        self.assertEqual(self.query("MATCH (:Well {name: $well})-[:HAS_DAY]->(d)-[:HAS_EVENT]->(e) "
                                    "RETURN count(DISTINCT d) AS days, count(e) AS events", well=self.well), days)


class EventLoaderTests(Neo4jCase):
    def write_events(self, folder: str, count: int) -> Path:
        recorded = json.loads(events_loader.EVENTS.read_text(encoding="utf-8"))
        path = Path(folder) / "events.json"
        path.write_text(json.dumps({**recorded, "events": recorded["events"][:count]}), encoding="utf-8")
        return path

    def test_loads_under_another_well_without_plans_twice(self):
        before = self.others()
        with tempfile.TemporaryDirectory() as folder:
            path = self.write_events(folder, 6)
            first = events_loader.load(path, [], self.well, dsn=UNREACHABLE_DSN)
            second = events_loader.load(path, [], self.well, dsn=UNREACHABLE_DSN)
        self.assertEqual(first, second)
        self.assertEqual((first["well"], first["events"], first["events_same"], first["plans"]), (self.well, 6, 6, 0))
        self.assertEqual(first["k1_chunks"], 0)  # E28's events cite the corpus export's IDs
        self.assertEqual(self.others(), before)

    def test_a_failed_check_rolls_the_load_back(self):
        with tempfile.TemporaryDirectory() as folder:
            events_loader.load(self.write_events(folder, 2), [], self.well, dsn=UNREACHABLE_DSN)
            wrong = "RETURN 'nothing' AS code, 0.0 AS hours"
            with mock.patch.object(events_loader, "HOURS_BY_CODE", wrong):
                with self.assertRaisesRegex(events_loader.CheckFailed, "hours by code"):
                    events_loader.load(self.write_events(folder, 5), [], self.well, dsn=UNREACHABLE_DSN)
        count = self.query("MATCH (:Well {name: $well})-[:HAS_DAY]->()-[:HAS_EVENT]->(e) RETURN count(e) AS n",
                           well=self.well)
        self.assertEqual(count, [{"n": 2}])


if __name__ == "__main__":
    unittest.main()
