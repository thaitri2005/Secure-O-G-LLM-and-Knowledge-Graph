"""Exercise query CLI output and containment without a build or manifest."""
from __future__ import annotations

import json
import shutil
import unittest

from helpers import PROJECT_ROOT, clean_dir, run_kgb


class QueryCliTest(unittest.TestCase):
    def setUp(self):
        self.run = clean_dir(PROJECT_ROOT / "runs/_test/query_cli")
        shutil.copyfile(PROJECT_ROOT / "tests/fixtures/graph_small.json", self.run / "graph.json")

    def test_alias_temporal_and_missing_path(self):
        result = run_kgb(["query", "--run", str(self.run), "alias", "International Business Machines"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("IBM", result.stdout)
        result = run_kgb(["query", "--run", str(self.run), "--json", "at", "--subject", "Alice",
                          "--predicate", "works_at", "--at", "2022"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)[0]["object"], "Acme Labs")
        result = run_kgb(["query", "--run", str(self.run), "path", "--from", "Alice", "--to", "Nobody"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "no path")

    def test_invalid_runs(self):
        missing = clean_dir(PROJECT_ROOT / "runs/_test/query_missing")
        missing.rmdir()
        for run in [str(missing), "tests/fixtures"]:
            with self.subTest(run=run):
                result = run_kgb(["query", "--run", run, "alias", "IBM"])
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_evidence_and_empty_alias(self):
        result = run_kgb(["query", "--run", str(self.run), "--json", "evidence", "--statement", "s1"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)[0]["support_count"], 1)
        result = run_kgb(["query", "--run", str(self.run), "alias", "Nobody"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "no result")


if __name__ == "__main__":
    unittest.main()
