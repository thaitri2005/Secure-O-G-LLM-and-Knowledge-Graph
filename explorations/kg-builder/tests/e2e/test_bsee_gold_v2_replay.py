"""Replay published BSEE variants and compare graph exports exactly."""
from __future__ import annotations

import json
import subprocess
import unittest

from helpers import assert_graph_equivalent, PROJECT_ROOT, clean_dir, run_kgb
from kgbuilder.core.text import read_jsonl, sha256_file


class BseeGoldV2ReplayTest(unittest.TestCase):
    def _replay_dev(self, name):
        if not (PROJECT_ROOT / "data/benchmarks/bsee_text/v2/selection.json").is_file():
            self.fail("Required published BSEE corpus is missing")
        fixtures = [PROJECT_ROOT / "data/fixtures/llm/bsee_text_dev_v2_guided.jsonl"]
        if name != "guided":
            fixtures.append(PROJECT_ROOT / f"data/fixtures/llm/bsee_text_dev_v2_{name}.jsonl")
        for fixture in fixtures:
            self.assertTrue(fixture.is_file(), str(fixture))
        output = clean_dir(PROJECT_ROOT / f"runs/_test/bsee_text_dev_v2_{name}_replay")
        cache = clean_dir(PROJECT_ROOT / f"runs/_test/bsee_text_dev_v2_{name}_cache") / "no_cache.jsonl"
        result = run_kgb([
            "run", "--config", f"configs/experiments/bsee_text_dev_v2_{name}_demo.yaml", "--mock",
            "--set", "llm.replay_logs=[" + ",".join(p.as_posix() for p in fixtures) + "]",
            "--set", f"llm.cache_path={cache.as_posix()}", "--out", str(output)],
            timeout=1800, test_id=f"bsee_text_dev_v2_{name}_replay")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(cache.exists())
        for level in ("A0", "A4"):
            root = output / f"bsee_text_dev_v2_{name}" / level
            recorded = PROJECT_ROOT / f"runs/reference/bsee_text/dev_v2_{name}/bsee_text_dev_v2_{name}" / level
            for filename in ("graph.json", "graph_strict.json"):
                if filename == "graph_strict.json" and not (recorded / filename).exists():
                    self.assertFalse((root / filename).exists())
                else:
                    self.assertTrue((root / filename).is_file())
                    assert_graph_equivalent(self, root / filename, recorded / filename)
            self.assertEqual(json.loads((root / "metrics.json").read_text(encoding="utf-8"))["llm"]["cache_misses"], 0)
            self.assertFalse(any(row.get("miss") for row in read_jsonl(root / "llm_calls.jsonl")))

    def test_dev_guided(self):
        self._replay_dev("guided")

    def test_dev_guided_windows(self):
        self._replay_dev("guided_windows")

    def test_dev_guided_groups(self):
        self._replay_dev("guided_groups")

    def test_dev_guided_recall(self):
        self._replay_dev("guided_recall")

    def _replay_test(self, name):
        if not (PROJECT_ROOT / "data/benchmarks/bsee_text/v2/selection.json").is_file():
            self.fail("Required published BSEE corpus is missing")
        fixtures = [PROJECT_ROOT / "data/fixtures/llm/bsee_text_test_v2_guided.jsonl"]
        if name == "guided_recall":
            fixtures.append(PROJECT_ROOT / "data/fixtures/llm/bsee_text_test_v2_guided_recall.jsonl")
        for fixture in fixtures:
            self.assertTrue(fixture.is_file(), str(fixture))
        output = clean_dir(PROJECT_ROOT / f"runs/_test/bsee_text_test_v2_{name}_replay")
        cache = clean_dir(PROJECT_ROOT / f"runs/_test/bsee_text_test_v2_{name}_cache") / "no_cache.jsonl"
        # The wrapper loads the offline environment; all test writes stay in runs/_test.
        result = subprocess.run([
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PROJECT_ROOT / "kgb.ps1"),
            "run", "--config", f"configs/experiments/bsee_text_test_v2_{name}_demo.yaml", "--mock",
            "--set", "llm.replay_logs=[" + ",".join(p.as_posix() for p in fixtures) + "]",
            "--set", f"llm.cache_path={cache.as_posix()}", "--out", str(output)],
            cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=1800)
        self.assertEqual(result.returncode, 0, "BSEE test replay command failed")
        self.assertFalse(cache.exists())
        for level in ("A0", "A4"):
            root = output / f"bsee_text_test_v2_{name}" / level
            recorded = PROJECT_ROOT / f"runs/reference/bsee_text/test_v2_{name}/bsee_text_test_v2_{name}" / level
            for filename in ("graph.json", "graph_strict.json"):
                if filename == "graph_strict.json" and not (recorded / filename).exists():
                    self.assertFalse((root / filename).exists())
                else:
                    self.assertTrue((root / filename).is_file())
                    assert_graph_equivalent(self, root / filename, recorded / filename)
            self.assertEqual(json.loads((root / "metrics.json").read_text(encoding="utf-8"))["llm"]["cache_misses"], 0)
            self.assertFalse(any(row.get("miss") for row in read_jsonl(root / "llm_calls.jsonl")))

    def test_test_guided(self):
        self._replay_test("guided")

    def test_test_guided_recall(self):
        self._replay_test("guided_recall")
