"""Induction CLI, replay precedence, and pre-write input validation."""
from __future__ import annotations

import json
import unittest

from helpers import PROJECT_ROOT, clean_dir, fake_lmstudio, replay_set, run_kgb
from kgbuilder.core.text import read_jsonl, write_json, write_jsonl


class InduceCliTest(unittest.TestCase):
    def test_live_replay_and_errors(self):
        root = clean_dir(PROJECT_ROOT / "runs/_test/induce_cli")
        source = root / "src"
        source.mkdir()
        graph = json.loads((PROJECT_ROOT / "tests/fixtures/graph_small.json").read_text(encoding="utf-8"))
        write_json(source / "graph.json", graph)
        write_json(source / "edc/request.json", {"enrich_schema": True})
        write_jsonl(source / "canonical.jsonl", [{"candidate_id": c, "predicate": s["predicate"],
                    "open_predicate": "runs" if s["statement_id"] == "s3" else s["predicate"],
                    "edc_definition": "The subject person works at the object organization."}
                    for s in graph["statements"] for c in s["candidate_ids"]])
        common = ["induce", "--config", "configs/experiments/showcase_noschema.yaml", "--run", str(source),
                  "--set", "induce.max_entities=2", *replay_set()]
        def run(extra, identity, expected):
            cache = clean_dir(PROJECT_ROOT / ".cache/tmp/tests" / identity) / "no_cache.jsonl"
            result = run_kgb(common + extra, test_id=identity, timeout=600)
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
            self.assertFalse(cache.exists())
            return result
        with fake_lmstudio(lambda body: "organization, company" if "ENTITY: Acme Labs" in body["prompt"] else "person, employee") as (url, received):
            run(["--out", str(root / "live"), "--set", "llm.base_url=" + url, "--set", "llm.cache=off"], "induce_cli_live", 0)
        self.assertEqual(len(received), 2)
        self.assertTrue(all("You are a helpful AI assistant." in body["prompt"] for _, body in received))
        self.assertTrue(all(any("ENTITY: " + name in b["prompt"] for _, b in received) for name in ["Acme Labs", "Alice"]))
        for filename in ["schema_induced.yaml", "relations.jsonl", "concepts.jsonl", "summary.json"]:
            self.assertTrue((root / "live" / filename).is_file())
        self.assertFalse(any(r.get("allowed") is False for r in read_jsonl(root / "live/net.jsonl")))
        run(["--out", str(root / "replay"), "--mock", *replay_set("runs/_test/induce_cli/live/llm_calls.jsonl")], "induce_cli_replay", 0)
        self.assertEqual((root / "live/schema_induced.yaml").read_bytes(), (root / "replay/schema_induced.yaml").read_bytes())
        self.assertEqual(json.loads((root / "replay/summary.json").read_text())["llm"]["cache_misses"], 0)
        result = run(["--out", str(root / "miss"), "--mock", "--set", "llm.replay_logs=[data/fixtures/llm/showcase_kggen.jsonl]"], "induce_cli_miss", 5)
        self.assertIn("provide the recorded schema induction fixture", result.stderr)
        self.assertNotIn("concept calls failed", result.stderr)
        result = run(["--out", str(root), "--overwrite", "--mock"], "induce_cli_ancestor", 2)
        self.assertIn("must not overlap", result.stderr)
        self.assertTrue((source / "graph.json").is_file())
        for i, extra in enumerate([["--run", "tests/fixtures"], ["--out", str(source)], ["--run", str(root / "live")]]):
            run(["--out", str(root / f"error{i}"), "--mock", *extra], f"induce_cli_error{i}", 2)
            self.assertFalse((root / f"error{i}").exists())
