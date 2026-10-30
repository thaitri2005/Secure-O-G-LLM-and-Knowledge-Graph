"""Fake-server judge v2 acceptance and hermetic replay of its answers."""
from __future__ import annotations

import json
import unittest

from helpers import PROJECT_ROOT, SENTENCE_GROUNDING, WINDOW_GROUNDING, clean_dir, fake_lmstudio, replay_set, run_kgb, sets
from kgbuilder.core.text import read_jsonl, sha256_file


class JudgeV2CliTest(unittest.TestCase):
    def test_v2_and_replay(self):
        root = clean_dir(PROJECT_ROOT / "runs/_test/judge_v2")
        for name in ("judge_v2_live", "judge_v2_replay"):
            clean_dir(PROJECT_ROOT / ".cache/tmp/tests" / name)
        def build(level, out, extra, test_id):
            result = run_kgb(["build", "--config", "configs/experiments/showcase.yaml", "--ablation", level,
                              *sets(WINDOW_GROUNDING), *extra, "--out", str(out), "--overwrite"], timeout=900, test_id=test_id)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with fake_lmstudio(lambda body: "No." if "Statement: IBM part of research division" in body["prompt"] else "Yes.") as (base, received):
            build("A5", root / "A5", ["--set", "llm.base_url=" + base, "--set", "llm.cache=readwrite", *replay_set()], "judge_v2_live")
            rows = read_jsonl(root / "A5/judge.jsonl")
            self.assertEqual(len(received), len({r["prompt"] for r in rows}))
            self.assertTrue(all("Is the following statement supported" in body["prompt"] for _, body in received))
            self.assertTrue(all(body["max_tokens"] == 32 for _, body in received))
        bad = next(r for r in rows if r["subject"] == "IBM" and r["predicate"] == "part_of" and r["object"] == "research division")
        self.assertIn("canon_changed", bad["risk"])
        build("A4", root / "A4", ["--mock", *replay_set()], "judge_v2_a4")
        metrics = json.loads((root / "A5/metrics.json").read_text(encoding="utf-8"))
        self.assertEqual(metrics["statements_accepted"], json.loads((root / "A4/metrics.json").read_text(encoding="utf-8"))["statements_accepted"])
        result = run_kgb(["eval", "showcase", "--run", str(root / "A5")], timeout=900)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        checks = json.loads((root / "A5/eval/showcase_checks.json").read_text(encoding="utf-8"))
        self.assertEqual(checks["details"]["G6"]["flagged"], [bad["statement_id"]])
        for check in ("G1", "G2", "G3", "G5", "G6"):
            self.assertEqual(checks["status"][check], "PASS")
        self.assertEqual(checks["status"]["G4"], dict.fromkeys(("q1", "q2", "q3", "q4"), "PASS"))
        for filename, included in (("graph.json", True), ("graph_strict.json", False)):
            graph = json.loads((root / "A5" / filename).read_text(encoding="utf-8"))
            self.assertEqual(bad["statement_id"] in {s["statement_id"] for s in graph["statements"]}, included)
        build("A5", root / "replay", ["--mock", *replay_set("runs/_test/judge_v2/A5/llm_calls.jsonl")], "judge_v2_replay")
        self.assertEqual(sha256_file(root / "A5/graph.json"), sha256_file(root / "replay/graph.json"))
        self.assertEqual(json.loads((root / "replay/metrics.json").read_text(encoding="utf-8"))["llm"]["cache_misses"], 0)

    def test_v1_reparse(self):
        if not (PROJECT_ROOT / "data/fixtures/llm/schema_induction_ablation_sentence.jsonl").is_file():
            self.fail("Required published test input is missing")
        clean_dir(PROJECT_ROOT / ".cache/tmp/tests/judge_v1r")
        out = clean_dir(PROJECT_ROOT / "runs/_test/judge_v1r")
        result = run_kgb(["build", "--config", "configs/experiments/showcase.yaml", "--ablation", "A5", "--mock",
                          *sets([p for p in SENTENCE_GROUNDING if not p.startswith("judge.version=")]), "--set", "judge.version=v1_reparse",
                          "--out", str(out), "--overwrite"], timeout=900, test_id="judge_v1r")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
        self.assertEqual(metrics["rejected_by_reason"]["judge_no"], 2)
        self.assertEqual(metrics["llm"]["cache_misses"], 0)


if __name__ == "__main__":
    unittest.main()
