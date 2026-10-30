"""Offline EDC extraction, provenance, evaluation and reproducible output."""
from __future__ import annotations

import json
import unittest
from helpers import PROJECT_ROOT, SENTENCE_GROUNDING, sets, clean_dir, run_kgb
from kgbuilder.core.text import read_jsonl, sha256_file
from kgbuilder.runtime.onprem import blocked_count


class ExtractBackendTest(unittest.TestCase):
    def build(self, level, name, extra=()):
        out = clean_dir(PROJECT_ROOT / "runs/_test" / name)
        result = run_kgb(["build", "--config", "configs/experiments/webnlg10.yaml", "--ablation", level,
                          "--mock", *sets(SENTENCE_GROUNDING), "--out", str(out), *extra], test_id=name)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
        self.assertEqual(metrics["llm"]["cache_misses"], 0)
        return out, metrics

    def check_logs(self, out, names):
        for name in names:
            path = out / name
            self.assertTrue(path.is_file(), path)
            self.assertEqual(blocked_count(path), 0, path.read_text(encoding="utf-8"))

    def test_edc_a0(self):
        out, metrics = self.build("A0", "edc_a0")
        self.assertEqual(metrics["llm"]["calls"], 10)
        self.assertEqual(metrics["grounding"], {"exact": 19, "partial": 13, "none": 1})
        self.assertTrue(all(c["extractor"] == "edc" for c in read_jsonl(out / "candidates.jsonl")))
        routes = read_jsonl(out / "routes.jsonl")
        self.assertEqual(len(routes), 10)
        self.assertTrue(all(r["backend"] == "edc" and r["score"] is None for r in routes))
        self.check_logs(out, ["net.jsonl", "net_edc_oie.jsonl"])

    def test_edc_a4_and_determinism(self):
        out, metrics = self.build("A4", "edc_a4")
        self.assertEqual(metrics["grounding"], {"exact": 19, "partial": 13, "none": 1})
        self.assertEqual(metrics["rejected_by_reason"], {"weak_evidence": 1})
        self.assertEqual(metrics["statements_accepted"], 30)
        result = run_kgb(["eval", "webnlg", "--run", str(out)], timeout=1800)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        scores = json.loads((out / "eval/scores.json").read_text(encoding="utf-8"))
        self.assertTrue(0 <= scores["strict"]["F1"] <= 1)
        docs = {d["doc_id"]: d["text"] for d in read_jsonl(out / "documents.jsonl")}
        for statement in read_jsonl(out / "statements.jsonl"):
            ev = statement["evidence_span"]
            self.assertEqual(statement["source_doc_id"], ev["doc_id"])
            self.assertEqual(docs[ev["doc_id"]][ev["char_start"]:ev["char_end"]], ev["text"])
            self.assertTrue(set("source_doc_id evidence_span valid_from valid_to extractor_version".split()) <= statement.keys())
        self.check_logs(out, ["net.jsonl", "net_edc.jsonl", "net_edc_oie.jsonl", "eval/net_eval.jsonl"])
        second, _ = self.build("A4", "edc_a4b")
        self.assertEqual(sha256_file(out / "graph.json"), sha256_file(second / "graph.json"))

    def test_bad_backend(self):
        result = run_kgb(["build", "--config", "configs/experiments/showcase.yaml", "--ablation", "A4", "--mock",
                          "--set", "extract.backend=bogus", "--out", "runs/_test/bad_backend"])
        self.assertEqual(result.returncode, 2)
        self.assertIn("extract.backend", result.stderr)

    def test_auto_a4(self):
        out, _ = self.build("A4", "auto_a4", ["--set", "extract.backend=auto"])
        routes = read_jsonl(out / "routes.jsonl")
        self.assertEqual(len(routes), 10)
        self.assertTrue(all(isinstance(r["score"], float) for r in routes))
        by_doc = {r["doc_id"]: r["backend"] for r in routes}
        for c in read_jsonl(out / "candidates.jsonl"):
            self.assertEqual(c["extractor"], by_doc[c["source_doc_id"]])
        result = run_kgb(["eval", "webnlg", "--run", str(out)], timeout=1800)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__": unittest.main()
