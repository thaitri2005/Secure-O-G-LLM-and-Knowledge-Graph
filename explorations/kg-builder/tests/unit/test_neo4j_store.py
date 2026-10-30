"""Exercise Neo4j projection, batching and run guards with an injected fake driver."""
from __future__ import annotations

import re
import unittest
from datetime import date

from helpers import PROJECT_ROOT
from kgbuilder.adapters.neo4j_store import (Neo4jGraphStore, build_queries, demo_params,
                                            demo_queries, make_run_id, rel_type)
from kgbuilder.core.config import KgbError
from kgbuilder.core.contracts import GraphRecord, Mention


class FakeResult:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def __iter__(self):
        return iter(self.rows)

    def single(self):
        return self.rows[0] if self.rows else None

    def consume(self):
        return None


class FakeTx:
    def __init__(self, driver):
        self.driver = driver

    def run(self, query, **params):
        self.driver.calls.append(("tx", query, params))
        if "SET m.run_id" in query:
            self.driver.run_id = params["run_id"]
        if self.driver.query_error:
            raise self.driver.query_error
        return FakeResult()


class FakeSession:
    def __init__(self, driver):
        self.driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def run(self, query, **params):
        self.driver.calls.append(("run", query, params))
        if self.driver.query_error:
            raise self.driver.query_error
        if "RETURN m.run_id" in query:
            return FakeResult([] if self.driver.run_id is None else [{"run_id": self.driver.run_id}])
        if "DETACH DELETE" in query:
            self.driver.run_id = None
        if "labels(n)" in query:
            return FakeResult([{"label": "Entity", "n": 4}, {"label": "Document", "n": 2},
                               {"label": "Chunk", "n": 2}, {"label": "KgbMeta", "n": 1}])
        if "type(r) AS type" in query:
            return FakeResult([{"type": "WORKS_AT", "n": 2}, {"type": "OPERATES", "n": 1}])
        return FakeResult(self.driver.demo_rows)

    def execute_write(self, fn, *args):
        self.driver.writes += 1
        return fn(FakeTx(self.driver), *args)


class FakeDriver:
    def __init__(self, run_id=None, verify_error=None, query_error=None):
        self.run_id, self.verify_error, self.query_error = run_id, verify_error, query_error
        self.calls, self.writes, self.closed, self.demo_rows = [], 0, False, []
        self.databases = []

    def verify_connectivity(self):
        if self.verify_error:
            raise self.verify_error

    def session(self, *, database):
        self.databases.append(database)
        return FakeSession(self)

    def close(self):
        self.closed = True


class Neo4jStoreTest(unittest.TestCase):
    def setUp(self):
        self.record = GraphRecord.model_validate_json((PROJECT_ROOT / "tests/fixtures/graph_small.json").read_text(encoding="utf-8"))
        self.sha = "1234567890abcdef" * 4

    def store(self, driver):
        return Neo4jGraphStore("bolt://127.0.0.1:7687", "neo4j", "test-only", "neo4j", 1, driver=driver)

    def test_rel_type(self):
        for predicate, expected in [("works_at", "WORKS_AT"), ("birthPlace", "BIRTH_PLACE"),
                                     ("was born in", "WAS_BORN_IN"), ("123", "RELATED_TO"),
                                     ("", "RELATED_TO"), ("x" * 65, "RELATED_TO")]:
            self.assertEqual(rel_type(predicate), expected)
        self.assertRegex(rel_type("x`]->() DETACH DELETE n //"), r"^[A-Z][A-Z0-9_]{0,63}$")

    def test_parameterization_and_batching(self):
        data = self.record.model_dump(mode="json")
        data["entities"][2]["name"] = "Nova_AI"
        record = GraphRecord.model_validate(data)
        queries = build_queries(record, [], "test_run_7f3a", 1)
        values = ["test_run_7f3a", *[e.name for e in record.entities],
                  *[a for e in record.entities for a in e.aliases],
                  *[s.statement_id for s in record.statements], *[d.text for d in record.documents],
                  *[t for s in record.statements for t in (s.valid_from, s.valid_to) if t is not None]]
        for query, params in queries:
            for value in values:
                self.assertNotIn(value, query)
            for identifier in re.findall(r"`([^`]*)`", query):
                self.assertRegex(identifier, r"^[A-Z][A-Z0-9_]{0,63}$")
            self.assertEqual(query.count("`"), 2 * len(re.findall(r"`[^`]*`", query)))
            if "rows" in params:
                self.assertEqual(len(params["rows"]), 1)
                self.assertEqual(set(params), {"rows"})
        entity_queries = [(q, p) for q, p in queries if "MERGE (e:Entity" in q]
        self.assertEqual(len(entity_queries), len(record.entities))
        self.assertEqual(entity_queries[2][1]["rows"][0]["props"]["keys"], ["nova ai"])
        self.assertTrue(any("`WORKS_AT`" in q for q, _ in queries))
        self.assertTrue(any("`OPERATES`" in q for q, _ in queries))
        self.assertIn("KgbMeta", queries[-1][0])
        self.assertEqual(queries[-1][1], {"run_id": "test_run_7f3a", "format": "kgb.graph/1"})
        self.assertEqual(make_run_id(record, self.sha), "small/A4/1234567890ab")
        props = next(p["rows"][0]["props"] for q, p in queries if "`WORKS_AT`" in q)
        self.assertEqual(props["valid_from"], date(2021, 1, 1))
        self.assertEqual(props["valid_to"], date(2024, 1, 1))
        self.assertEqual(props["valid_from_text"], "2021")
        for _, params in queries:
            for row in params.get("rows", []):
                self.assertNotIn(None, row.get("props", {}).values())

    def test_mentions_join_and_rejected_statements(self):
        entity = self.record.entities[0].model_copy(update={"mention_ids": ["unknown", "m1"]})
        record = self.record.model_copy(update={"entities": [entity, *self.record.entities[1:]],
                                                "statements": [s.model_copy(update={"status": "rejected"})
                                                               for s in self.record.statements]})
        mention = Mention(mention_id="m1", chunk_id="d1#c000", surface="Alice",
                          char_start=6, char_end=11, extractor_version="test")
        queries = build_queries(record, [mention], "test", 500)
        rows = [p["rows"] for q, p in queries if "[m:MENTIONS]" in q]
        self.assertEqual(rows, [[{"entity_id": "e1", "chunk_id": "d1#c000", "surface": "Alice"}]])
        self.assertFalse(any("statement_id: row.statement_id" in q for q, _ in queries))

    def test_different_run_guard_before_any_write(self):
        driver = FakeDriver(run_id="different")
        with self.assertRaises(KgbError) as caught:
            self.store(driver).load(self.record, [], self.sha, wipe=False)
        self.assertEqual(caught.exception.code, 7)
        self.assertEqual(driver.writes, 0)
        self.assertEqual(len(driver.calls), 1)
        self.assertIn("RETURN m.run_id", driver.calls[0][1])

    def test_wipe_constraints_and_reload(self):
        driver = FakeDriver(run_id="different")
        store = self.store(driver)
        store.verify()
        counts = store.load(self.record, [], self.sha, wipe=True)
        self.assertIn("DETACH DELETE", driver.calls[1][1])
        self.assertEqual(driver.calls[1][0], "run")
        self.assertEqual(sum("CREATE CONSTRAINT" in q for _, q, _ in driver.calls), 3)
        self.assertEqual(sum("CREATE INDEX" in q for _, q, _ in driver.calls), 1)
        self.assertEqual(counts["nodes"]["Entity"], 4)
        self.assertEqual(counts["relationships"]["WORKS_AT"], 2)
        first_batches = [(q, p) for mode, q, p in driver.calls if mode == "tx"]
        driver.calls.clear()
        self.assertEqual(store.load(self.record, [], self.sha, wipe=False), counts)
        self.assertEqual(first_batches, [(q, p) for mode, q, p in driver.calls if mode == "tx"])
        self.assertFalse(any("DETACH DELETE" in q for _, q, _ in driver.calls))
        self.assertTrue(all("MERGE" in q for mode, q, _ in driver.calls if mode == "tx"))
        self.assertEqual(driver.databases, ["neo4j", "neo4j"])
        store.close()
        self.assertTrue(driver.closed)

    def test_verify_and_query_errors(self):
        from neo4j.exceptions import CypherSyntaxError, ServiceUnavailable
        store = self.store(FakeDriver(verify_error=ServiceUnavailable("down")))
        with self.assertRaises(KgbError) as caught:
            store.verify()
        self.assertEqual(caught.exception.code, 7)
        self.assertIn("bolt://127.0.0.1:7687", str(caught.exception))
        store = self.store(FakeDriver(query_error=CypherSyntaxError("bad query")))
        with self.assertRaises(KgbError) as caught:
            store.load(self.record, [], self.sha, False)
        self.assertEqual(caught.exception.code, 7)
        with self.assertRaises(KgbError) as caught:
            store.demo("works_at", {"sid": "s1"})
        self.assertEqual(caught.exception.code, 7)

    def test_demo_queries_and_params(self):
        params = demo_params("International Business Machines", "Alice", "2022", "s1", "Alan Turing", "London")
        self.assertEqual(params, {"qkey": "international business machines", "skey": "alice", "at": "2022-01-01",
                                  "sid": "s1", "from_key": "alan turing", "to_key": "london"})
        queries = demo_queries("works_at")
        self.assertEqual([name for name, _ in queries], ["alias", "temporal", "provenance", "path"])
        for _, query in queries:
            for value in params.values():
                self.assertNotIn(value, query)
        self.assertIn("`WORKS_AT`", queries[1][1])
        self.assertIn("date($at) < r.valid_to", queries[1][1])
        driver = FakeDriver()
        driver.demo_rows = [{"value": "scripted"}]
        store = self.store(driver)
        self.assertEqual(store.demo("works_at", params), {name: driver.demo_rows for name, _ in queries})
        self.assertTrue(all(p == params for _, _, p in driver.calls))
        driver.calls.clear()
        self.assertEqual(store.demo("works_at", {**params, "sid": None})["provenance"], [])
        self.assertEqual(len(driver.calls), 3)


if __name__ == "__main__":
    unittest.main()
