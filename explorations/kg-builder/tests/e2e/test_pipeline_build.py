"""Build CLI contracts, deterministic replay, path policy, and health priorities."""
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from helpers import PROJECT_ROOT, METRIC_KEYS, clean_dir, run_kgb
from kgbuilder.core.config import KgbError, load_config
from kgbuilder.build.pipeline import check_health, llm_metrics, preflight, upstream_sha7
from kgbuilder.core.text import read_jsonl, sha256_file, write_jsonl


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/pipeline_build" / self._testMethodName)

    def command(self, out, extra=()):
        return run_kgb(["build", "--config", "configs/experiments/showcase.yaml", "--ablation", "A4", "--mock",
                        "--set", "flags.canon=false", "--out", str(out), *extra], test_id="pipeline_build")

    def test_build_artifacts_and_determinism(self):
        first = clean_dir(PROJECT_ROOT / "runs/_test/b1")
        second = clean_dir(PROJECT_ROOT / "runs/_test/b2")
        result = self.command(first)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        expected = ["manifest.json", "graph.json", "graph.graphml", "graph.html", "metrics.json",
                    "llm_calls.jsonl", "net.jsonl", "net_edc.jsonl", "run.log",
                    *[name + ".jsonl" for name in ["documents", "chunks", "mentions", "candidates",
                                                    "canonical", "entities", "statements", "rejected"]]]
        for name in expected:
            self.assertTrue((first / name).exists(), name)
        metrics = json.loads((first / "metrics.json").read_text(encoding="utf-8"))
        self.assertEqual(set(metrics), METRIC_KEYS)
        self.assertEqual(metrics["llm"], llm_metrics(first / "llm_calls.jsonl"))
        self.assertEqual(metrics["llm"]["cache_misses"], 0)
        self.assertEqual(metrics["llm"]["calls"], 6)
        documents = {r["doc_id"]: r["text"] for r in read_jsonl(first / "documents.jsonl")}
        for row in read_jsonl(first / "statements.jsonl"):
            self.assertTrue(set("source_doc_id evidence_span valid_from valid_to extractor_version".split()) <= set(row))
            evidence = row["evidence_span"]
            self.assertEqual(row["source_doc_id"], evidence["doc_id"])
            self.assertEqual(documents[evidence["doc_id"]][evidence["char_start"]:evidence["char_end"]], evidence["text"])
        result = self.command(second)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(sha256_file(first / "graph.json"), sha256_file(second / "graph.json"))
        self.assertEqual(self.command(first).returncode, 2)
        result = run_kgb(["eval", "showcase", "--run", str(first)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["exit_code"], 0)
        self.assertEqual(manifest["upstream"], upstream_sha7())

    def test_path_and_missing_replay(self):
        self.assertEqual(self.command("C:\\Windows\\Temp\\x").returncode, 2)
        output = clean_dir(PROJECT_ROOT / "runs/_test/unrecorded")
        result = self.command(output, ["--set", "corpus.path=tests/fixtures/corpus_unrecorded.jsonl"])
        self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
        metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
        self.assertGreater(metrics["llm"]["cache_misses"], 0)

    def test_health_priorities_and_ram(self):
        ok, bad = self.root / "core.jsonl", self.root / "worker.jsonl"
        write_jsonl(ok, [{"kind": "connect", "target": "127.0.0.1", "allowed": True}])
        write_jsonl(bad, [{"kind": "connect", "target": "example.invalid", "allowed": False}])
        with self.assertRaises(KgbError) as cm:
            check_health(SimpleNamespace(fatal="cache_miss:abc"), [ok, bad])
        self.assertEqual(cm.exception.code, 4)
        self.assertIn("example.invalid", str(cm.exception))
        for fatal, code in [("cache_miss:abc", 5), ("upstream errors", 6)]:
            with self.assertRaises(KgbError) as cm:
                check_health(SimpleNamespace(fatal=fatal), [ok])
            self.assertEqual(cm.exception.code, code)
        cfg = load_config(PROJECT_ROOT / "configs/experiments/showcase.yaml", mock=True)
        with patch("kgbuilder.build.pipeline.free_ram_bytes", return_value=1 << 30):
            warnings = preflight(cfg)
        self.assertTrue(any("RAM" in warning and "WARNING" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
