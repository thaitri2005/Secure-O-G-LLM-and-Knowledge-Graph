"""Check fresh offline output against the immutable pre-extractor routing baseline."""
from __future__ import annotations

import copy
import shutil
import unittest

import baseline
from helpers import PROJECT_ROOT, SENTENCE_GROUNDING, clean_dir, run_kgb, sets


class BaselineV2MockTest(unittest.TestCase):
    EXTRA = ["--set", "extract.backend=kggen"]
    FIXTURE = baseline.FIXTURE_V2

    @classmethod
    def setUpClass(cls):
        cls.out = clean_dir(PROJECT_ROOT / "runs/_test/baseline_mock" / cls.__name__)
        cls.result = run_kgb(["run", "--config", "configs/experiments/demo.yaml", "--mock", "--out", str(cls.out),
                              "--overwrite", *cls.EXTRA], test_id="baseline_mock", timeout=1800)

    def test_exit(self):
        self.assertEqual(self.result.returncode, 0, self.result.stdout + self.result.stderr)

    def test_baseline(self):
        self.assertEqual(baseline.compare(self.out, self.FIXTURE), [])

    def test_normalize_exact_fields(self):
        metrics = {"stage_seconds": {"extract": 1}, "docs": 2, "llm": {"seconds": 3, "cache_hits": 4,
                   "cache_misses": 0, "calls": 4, "prompt_tokens": 10}, "other": {"seconds": 8}}
        original = copy.deepcopy(metrics)
        self.assertEqual(baseline.normalize_metrics(metrics), {"docs": 2, "llm": {"calls": 4, "prompt_tokens": 10}, "other": {"seconds": 8}})
        self.assertEqual(metrics, original)

    def test_corrupt_fixture(self):
        target = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/baseline") / "fixture"
        shutil.copytree(baseline.FIXTURE_V2, target)
        rel = "showcase/A0/graph.json"
        path = target / rel
        content = path.read_bytes()
        path.write_bytes(bytes([content[0] ^ 1]) + content[1:])
        self.assertIn("CORRUPT " + rel, baseline.compare(self.out, target))


class BaselineV1LegacyTest(BaselineV2MockTest):
    EXTRA = ["--set", "extract.backend=kggen", *sets(SENTENCE_GROUNDING)]
    FIXTURE = baseline.FIXTURE_V1


if __name__ == "__main__": unittest.main()
