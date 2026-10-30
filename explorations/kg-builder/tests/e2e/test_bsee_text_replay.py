"""Replay the required BSEE benchmark capture and check both graph levels."""
from __future__ import annotations

import json
import unittest

from helpers import assert_graph_equivalent, PROJECT_ROOT, clean_dir, run_kgb
from kgbuilder.core.text import read_jsonl, sha256_file

OPTION = "A"


class BseeTextReplayTest(unittest.TestCase):
    def test_replay(self):
        if not (PROJECT_ROOT / "data/benchmarks/bsee_text/v1/selection.json").is_file():
            self.fail("Required published BSEE corpus is missing")
        fixture = PROJECT_ROOT / "data/fixtures/llm/bsee_text_test_subset_v1_base.jsonl"
        if not fixture.is_file():
            self.fail("Required recorded fixture is missing")
        output = clean_dir(PROJECT_ROOT / "runs/_test/bsee_replay")
        cache = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/bsee_replay") / "no_cache.jsonl"
        flags = ["--set", "corpus.limit=20"] if OPTION == "B" else []
        result = run_kgb(["run", "--config", "configs/experiments/bsee_text_test_subset_v1_base_demo.yaml", "--mock",
                          "--set", f"llm.replay_logs=[{fixture.as_posix()}]",
                          "--set", f"llm.cache_path={cache.as_posix()}", "--out", str(output), *flags], timeout=1800)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(cache.exists())
        for level in ("A0", "A4"):
            root = output / "bsee_text_test_subset_v1_base" / level
            recorded = PROJECT_ROOT / "runs/reference/bsee_text/test_subset_v1_base/bsee_text_test_subset_v1_base" / level
            for name in ("graph.json", "graph_strict.json"):
                if name == "graph_strict.json" and not (recorded / name).exists():
                    self.assertFalse((root / name).exists())
                else:
                    self.assertTrue((root / name).is_file())
                    assert_graph_equivalent(self, root / name, recorded / name)
            self.assertEqual(json.loads((root / "metrics.json").read_text())["llm"]["cache_misses"], 0)
            self.assertFalse(any(r.get("miss") for r in read_jsonl(root / "llm_calls.jsonl")))
