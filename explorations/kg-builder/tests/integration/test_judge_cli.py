"""A5 stage integration against a fake reader, G6, and hermetic replay."""
from __future__ import annotations

import json
import unittest

from helpers import PROJECT_ROOT, SENTENCE_GROUNDING, sets, LIVE_FIXTURE, clean_dir, fake_lmstudio, replay_set, run_kgb
from kgbuilder.core.text import read_jsonl, sha256_file
from kgbuilder.runtime.gateway import replay_gaps


class JudgeCliTest(unittest.TestCase):
    def setUp(self):
        if not LIVE_FIXTURE.is_file():
            self.fail("Required recorded fixture is missing")
        self.root = clean_dir(PROJECT_ROOT / "runs/_test/judge_cli")
        for identity in ("judge_cli_a5", "judge_cli_a4", "judge_cli_replay"):
            clean_dir(PROJECT_ROOT / ".cache/tmp/tests" / identity)

    def test_judge_and_replay(self):
        common = ["build", "--config", "configs/experiments/showcase.yaml", "--overwrite", *sets(SENTENCE_GROUNDING), *replay_set()]
        def run(args, identity):
            result = run_kgb(args, timeout=900, test_id=identity)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with fake_lmstudio(lambda b: "No, this is not true." if "Is this true: IBM part of research division?" in b["prompt"] else "Yes, this is true.") as (url, received):
            run(common + ["--ablation", "A5", "--set", "llm.base_url=" + url, "--set", "llm.cache=readwrite",
                          "--out", str(self.root / "A5")], "judge_cli_a5")
            self.assertEqual(len(received), 7)
            self.assertTrue(all("Is this true:" in body["prompt"] for _, body in received))
        metrics = json.loads((self.root / "A5/metrics.json").read_text())
        self.assertEqual(metrics["statements_accepted"], 6)
        self.assertEqual(metrics["rejected_by_reason"]["judge_no"], 1)
        self.assertEqual(metrics["judge_unparsed"], 0)
        run(["eval", "showcase", "--run", str(self.root / "A5")], "judge_cli_a5")
        checks = json.loads((self.root / "A5/eval/showcase_checks.json").read_text())["status"]
        self.assertTrue(all(checks[k] == "PASS" for k in ("G1", "G2", "G3", "G5", "G6")))
        self.assertEqual(set(checks["G4"].values()), {"PASS"})
        run(common + ["--ablation", "A4", "--mock", "--out", str(self.root / "A4")], "judge_cli_a4")
        run(["eval", "showcase", "--run", str(self.root / "A4")], "judge_cli_a4")
        report = json.loads((self.root / "A4/eval/showcase_checks.json").read_text())
        self.assertEqual(report["status"]["G6"], "FAIL")
        self.assertEqual(len(report["details"]["G6"]["reversed"]), 1)
        self.assertFalse((self.root / "A4/judge.jsonl").exists())
        run(common + ["--ablation", "A5", "--mock", *replay_set("runs/_test/judge_cli/A5/llm_calls.jsonl"),
                      "--out", str(self.root / "A5_replay")], "judge_cli_replay")
        self.assertEqual(json.loads((self.root / "A5_replay/metrics.json").read_text())["llm"]["cache_misses"], 0)
        self.assertEqual(sha256_file(self.root / "A5/graph.json"), sha256_file(self.root / "A5_replay/graph.json"))
        for identity in ("judge_cli_a4", "judge_cli_replay"):
            self.assertFalse((PROJECT_ROOT / ".cache/tmp/tests" / identity / "no_cache.jsonl").exists())

    def test_tolerated_error_is_not_replayable(self):
        for identity in ("judge_gap_live", "judge_gap_replay"):
            clean_dir(PROJECT_ROOT / ".cache/tmp/tests" / identity)
        common = ["build", "--config", "configs/experiments/showcase.yaml", "--ablation", "A5", "--overwrite", *sets(SENTENCE_GROUNDING)]
        with fake_lmstudio(lambda b: 500 if "Is this true: IBM part of research division?" in b["prompt"]
                           else "Yes, this is true.") as (url, received):
            result = run_kgb([*common, *replay_set(), "--set", "llm.base_url=" + url,
                              "--set", "llm.cache=readwrite", "--out", str(self.root / "gap")],
                             test_id="judge_gap_live", timeout=900)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(len(received), 7)
        self.assertEqual(json.loads((self.root / "gap/metrics.json").read_text())["judge_errors"], 1)
        log = self.root / "gap/llm_calls.jsonl"
        self.assertEqual(sum(r.get("stage") == "judge" and r.get("content") is None for r in read_jsonl(log)), 1)
        gaps = replay_gaps([log])
        self.assertEqual(gaps["failed_rows"], 1)
        self.assertEqual(len(gaps["unreplayable"]), 1)
        self.assertEqual(gaps["unreplayable"][0]["stage"], "judge")
        result = run_kgb(["fixtures", "--from", str(self.root / "gap"),
                          "--to", str(self.root / "gap_fixture.jsonl")], timeout=900)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = run_kgb([*common, "--mock", *replay_set("runs/_test/judge_cli/gap_fixture.jsonl"),
                          "--out", str(self.root / "gap_replay")], test_id="judge_gap_replay", timeout=900)
        self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
        misses = [r for r in read_jsonl(self.root / "gap_replay/llm_calls.jsonl") if r.get("miss")]
        self.assertTrue(misses)
        self.assertEqual(misses[0]["stage"], "judge")
        self.assertFalse((PROJECT_ROOT / ".cache/tmp/tests/judge_gap_replay/no_cache.jsonl").exists())
