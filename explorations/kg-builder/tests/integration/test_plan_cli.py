"""Offline plan CLI counts leaf misses without contacting a fake upstream."""
from __future__ import annotations

import json
import unittest

from helpers import PROJECT_ROOT, SENTENCE_GROUNDING, sets, clean_dir, fake_lmstudio, replay_set, run_kgb
from kgbuilder.core.text import read_jsonl


class PlanCliTest(unittest.TestCase):
    def test_a5(self):
        out = clean_dir(PROJECT_ROOT / "runs/_plan/test_a5")
        clean_dir(PROJECT_ROOT / ".cache/tmp/tests/plan_a5")
        gets = []
        def metadata(path):
            gets.append(path)
            return {}
        with fake_lmstudio(["must not be used"], metadata=metadata) as (url, received):
            proc = run_kgb(["build", "--config", "configs/experiments/showcase.yaml", "--ablation", "A5", *sets(SENTENCE_GROUNDING),
                            "--set", "llm.cache=plan", "--set", "llm.base_url=" + url, *replay_set(),
                            "--out", str(out), "--overwrite"], test_id="plan_a5", timeout=1800)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual((received, gets), ([], []))
        proc = run_kgb(["analyze", "--plan", str(out)])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        report = json.loads((out / "plan_cost.json").read_text(encoding="utf-8"))
        self.assertEqual(report["kinds"]["judge"]["new_calls"], 7)
        self.assertEqual(report["total"]["new_calls"], 7)
        self.assertEqual(json.loads((out / "metrics.json").read_text())["judge_unparsed"], 7)
        self.assertTrue(all(r["stage"] == "judge" for r in read_jsonl(out / "llm_calls.jsonl") if r.get("planned")))

    def test_qa(self):
        self.assertTrue((PROJECT_ROOT / "runs/reference/ablation_sentence_grounding/2wiki10/A2").is_dir(),
                        "Required published reference graph is missing")
        out = clean_dir(PROJECT_ROOT / "runs/_plan/test_qa")
        clean_dir(PROJECT_ROOT / ".cache/tmp/tests/plan_qa")
        gets = []
        def metadata(path):
            gets.append(path)
            return {}
        with fake_lmstudio(["must not be used"], metadata=metadata) as (url, received):
            proc = run_kgb(["eval", "qa", "--config", "configs/experiments/twowiki10_qa_intermediate_graphs.yaml",
                            "--set", "llm.cache=plan", "--set", "llm.base_url=" + url,
                            "--out", str(out), "--overwrite"], test_id="plan_qa", timeout=1800)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual((received, gets), ([], []))
        rows = read_jsonl(out / "llm_calls.jsonl")
        self.assertFalse(any(r.get("planned") for r in rows if r["stage"] == "qa.text"))
        def keys(stage):
            return {r["key"] for r in rows if r.get("planned") and r["stage"] == stage}
        self.assertLessEqual(keys("qa.graph@A3"), keys("qa.graph@A2"))


if __name__ == "__main__":
    unittest.main()
