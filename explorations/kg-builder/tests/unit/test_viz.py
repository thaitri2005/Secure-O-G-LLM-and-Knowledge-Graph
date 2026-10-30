"""Accessible, self-contained graph and report rendering."""
from __future__ import annotations

import json
import re
import unittest

from helpers import PROJECT_ROOT, clean_dir
from kgbuilder.core.contracts import GraphRecord
from kgbuilder.build.publish.viz import graph_payload, layout, render_graph_html, render_report_html


class VizTest(unittest.TestCase):
    def setUp(self):
        self.root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/viz")
        self.record = GraphRecord.model_validate_json((PROJECT_ROOT / "tests/fixtures/graph_small.json").read_text(encoding="utf-8"))
        self.payload = graph_payload(self.record)

    def metrics(self):
        return {"entities": 4, "er_reduction": 0.1, "candidates": 3, "grounding": {"exact": 3},
                "canon": {"mapped_schema": 2, "inverse": 1, "sent": 3}, "statements_accepted": 3,
                "statements_rejected": 0, "temporal_statements": 1,
                "llm": {"calls": 2, "cache_hits": 1}}

    def test_graph_html(self):
        path = self.root / "graph.html"
        render_graph_html(self.record, path)
        text = path.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"https?://")
        self.assertIn('role="img"', text)
        self.assertIn("<label for=", text)
        self.assertEqual(len(re.findall(r"<tr data-statement=", text)), len(self.record.statements))
        data = re.search(r'<script type="application/json" id="kgb-data">(.*?)</script>', text, re.S).group(1)
        self.assertEqual(json.loads(data.replace("<\\/", "</")), self.payload)
        self.assertEqual(len(layout(self.record)), 4)
        self.assertEqual(layout(self.record), layout(self.record))
        for x, y in layout(self.record).values():
            self.assertTrue(40 <= x <= 960)
            self.assertTrue(40 <= y <= 660)

    def test_report_html(self):
        report = {"format": "kgb.demo/1", "name": "demo", "title": "KG builder demo: demo",
                  "levels": ["A0", "A4"], "runs": [{
                      "name": "showcase", "levels": {
                          level: {"exit_code": 0, "metrics": self.metrics(),
                                  "showcase": {"G1": "PASS", "G2": "FAIL", "G3": "PASS",
                                               "G4": {"q1": "FAIL", "q2": "PASS", "q3": "PASS", "q4": "FAIL"},
                                               "G5": "PASS", "gold_recall": 0.5},
                                  "payload": self.payload} for level in ("A0", "A4")}, "baseline": None}]}
        path = self.root / "report.html"
        report["runs"][0]["levels"]["A0"]["extract"] = {"backend": "kggen", "routes": []}
        report["runs"][0]["levels"]["A4"]["extract"] = {"backend": "edc", "routes": []}
        render_report_html(report, path)
        text = path.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"https?://")
        self.assertIn("Before (A0)", text)
        self.assertIn("<td>extract backend</td><td>kggen</td><td>edc</td>", text)
        self.assertIn("After (A4)", text)
        self.assertIn('role="img"', text)
        self.assertIn("<label for=", text)
        self.assertEqual(len(re.findall(r"<tr data-statement=", text)), 6)
        data = re.search(r'<script type="application/json" id="kgb-data">(.*?)</script>', text, re.S).group(1)
        self.assertEqual(json.loads(data.replace("<\\/", "</")), report)
        js = (PROJECT_ROOT / "src/kgbuilder/build/publish/assets/viz.js").read_text(encoding="utf-8")
        self.assertIn("click", js)
        self.assertIn("keydown", js)
        self.assertIn("time-filter", js)
        self.assertIn('time.addEventListener("input"', js)
        self.assertIn('event.key === "Enter"', js)

    def test_baseline_and_failed_level(self):
        scores = {kind: {"P": .8, "R": .9, "F1": .843} for kind in ("strict", "exact", "partial", "full_triple")}
        report = {"levels": ["A0", "A4"], "runs": [{"name": "webnlg10",
                  "baseline": {"label": "B-EDC", "webnlg": scores}, "levels": {
                      "A0": {"exit_code": 6, "metrics": None, "payload": None, "webnlg": None},
                      "A4": {"exit_code": 0, "metrics": self.metrics(), "webnlg": scores, "payload": self.payload}}}]}
        path = self.root / "failed.html"
        render_report_html(report, path)
        text = path.read_text(encoding="utf-8")
        self.assertIn("B-EDC", text)
        self.assertIn("<td>extract backend</td><td>FAILED (exit 6)</td><td>–</td>", text)
        self.assertIn("strict F1", text)
        self.assertEqual(text.count("<td>FAILED (exit 6)</td>"), 21)

        self.assertEqual(text.count('class="graph-panel"'), 1)
        self.assertEqual(len(re.findall(r"<tr data-statement=", text)), 3)

    def test_embedded_text_and_empty_graph(self):
        danger = 'https://localhost/</script><script>alert("x")</script>{{JS}}'
        record = self.record.model_copy(update={"run_name": danger, "entities": [
            e.model_copy(update={"name": danger}) if e.entity_id == "e1" else e for e in self.record.entities]})
        path = self.root / "escape.html"
        render_graph_html(record, path)
        text = path.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"https?://")
        self.assertNotIn('<script>alert("x")', text)
        data = re.search(r'<script type="application/json" id="kgb-data">(.*?)</script>', text, re.S).group(1)
        self.assertEqual(json.loads(data)["nodes"][0]["name"], danger)
        self.assertIn("&lt;/script&gt;", text)
        empty = self.record.model_copy(update={"statements": []})
        self.assertEqual(layout(empty), {})
        render_graph_html(empty, self.root / "empty.html")
        self.assertIn("0 entities, 0 statements", (self.root / "empty.html").read_text(encoding="utf-8"))

    def test_auto_routing_table(self):
        routes = [{"doc_id": "d1", "backend": "edc", "score": .4, "reason": "coverage>=tau"},
                  {"doc_id": "d2", "backend": "kggen", "score": .2, "reason": "coverage<tau"},
                  {"doc_id": "d3", "backend": "kggen", "score": None, "reason": "no_schema"}]
        report = {"levels": ["A0", "A4"], "runs": [{"name": "auto-test", "levels": {
            level: {"exit_code": 0, "metrics": self.metrics(), "payload": self.payload,
                    "extract": {"backend": "auto", "routes": routes}} for level in ("A0", "A4")}}]}
        path = self.root / "auto.html"
        render_report_html(report, path)
        text = path.read_text(encoding="utf-8")
        self.assertIn("auto (edc 1 / kggen 2)", text)
        table = re.search(r"<caption>Routing: auto-test</caption>.*?<tbody>(.*?)</tbody>", text, re.S).group(1)
        self.assertEqual(table.count("<tr>"), 3)
        self.assertIn("0.4000", table)
        self.assertIn("<td>–</td>", table)
        for d in report["runs"][0]["levels"].values(): d["extract"]["backend"] = "edc"
        render_report_html(report, path)
        self.assertNotIn("<caption>Routing:", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
