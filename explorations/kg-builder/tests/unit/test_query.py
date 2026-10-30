"""Graph query behavior over the small graph, without manifests or services."""
from __future__ import annotations

import shutil
import unittest

from helpers import PROJECT_ROOT, clean_dir
from kgbuilder.core.config import ConfigError
from kgbuilder.core.contracts import GraphRecord
from kgbuilder.core.text import cj
from kgbuilder.serve import query


class QueryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/query")
        shutil.copyfile(PROJECT_ROOT / "tests/fixtures/graph_small.json", self.tmp / "graph.json")
        self.record = query.load_graph(self.tmp)

    def test_load_and_alias(self):
        self.assertEqual([e.entity_id for e in query.alias(self.record, "international business machines")], ["e4"])
        self.assertEqual(query.alias(self.record, "nobody"), [])
        with self.assertRaises(ConfigError):
            query.load_graph(self.tmp / "missing")
        (self.tmp / "graph.json").write_text('{"format":"invalid"}', encoding="utf-8")
        with self.assertRaises(ConfigError):
            query.load_graph(self.tmp)

    def test_temporal(self):
        for time, expected in [("2022", ["Acme Labs"]), ("2024", ["Nova AI"]),
                               ("2025", ["Nova AI"]), (None, ["Acme Labs", "Nova AI"])]:
            with self.subTest(time=time):
                rows = query.at(self.record, "Alice", "works_at", time)
                self.assertEqual([r["object"] for r in rows], expected)
        with self.assertRaises(ConfigError):
            query.at(self.record, "Alice", "works_at", "22")

    def test_evidence(self):
        rows = query.evidence(self.record, statement_id="s1")
        self.assertEqual(rows, query.evidence(self.record, s="Alice", p="works_at", o="Acme Labs"))
        self.assertEqual(len(rows), 1)
        ev = self.record.statements[0].evidence[0]
        self.assertEqual(rows[0]["evidence"][0]["text"], self.record.documents[0].text[ev.char_start:ev.char_end])
        self.assertEqual(query.evidence(self.record, statement_id="missing"), [])
        with self.assertRaises(ConfigError):
            query.evidence(self.record, s="Alice")

    def test_path(self):
        rows = query.path(self.record, "Alice", "IBM")
        self.assertEqual([(r["from"], r["to"]) for r in rows], [("Alice", "Acme Labs"), ("Acme Labs", "IBM")])
        self.assertIsNone(query.path(self.record, "Alice", "IBM", max_hops=1))
        self.assertIsNone(query.path(self.record, "Alice", "nobody"))
        disconnected = self.record.model_copy(update={"statements": []})
        self.assertIsNone(query.path(disconnected, "Alice", "IBM"))

    def test_edc_names_and_parallel_edges(self):
        data = self.record.model_dump(mode="json")
        data["entities"][2]["name"] = "Nova_AI"
        r = GraphRecord.model_validate_json(cj(data))
        self.assertEqual([e.entity_id for e in query.alias(r, "Nova AI")], ["e3"])
        self.assertEqual(len(query.path(r, "Alice", "Nova AI")), 1)
        parallel = r.statements[0].model_copy(update={"statement_id": "a0"})
        rejected = r.statements[1].model_copy(update={"status": "rejected"})
        r = r.model_copy(update={"statements": [*r.statements, parallel, rejected]})
        self.assertEqual(query.path(r, "Alice", "Acme Labs")[0]["statement_id"], "a0")


if __name__ == "__main__":
    unittest.main()
