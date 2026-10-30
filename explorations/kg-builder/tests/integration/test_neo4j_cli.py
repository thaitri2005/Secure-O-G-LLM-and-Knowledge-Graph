"""Verify Neo4j CLI errors without starting or contacting a database server."""
from __future__ import annotations

import shutil
import unittest

from helpers import PROJECT_ROOT, clean_dir, run_kgb


class Neo4jCliTest(unittest.TestCase):
    def setUp(self):
        self.run = clean_dir(PROJECT_ROOT / "runs/_test/neo4j_cli")
        shutil.copyfile(PROJECT_ROOT / "tests/fixtures/graph_small.json", self.run / "graph.json")

    def test_missing_password(self):
        for mode in ("load", "demo"):
            result = run_kgb(["neo4j", mode, "--run", str(self.run)], timeout=120,
                             env_extra={"KGB_NEO4J_PASSWORD": ""})
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("KGB_NEO4J_PASSWORD", result.stderr)

    def test_closed_loopback_port(self):
        result = run_kgb(["neo4j", "load", "--run", str(self.run), "--set", "neo4j.uri=bolt://127.0.0.1:9"],
                         timeout=120, env_extra={"KGB_NEO4J_PASSWORD": "test-only"})
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
        self.assertIn("Neo4j không chạy", result.stderr)
        self.assertNotIn("test-only", result.stdout + result.stderr)

    def test_external_uri_and_containment(self):
        result = run_kgb(["neo4j", "load", "--run", str(self.run), "--set", "neo4j.uri=bolt://192.168.1.5:7687"],
                         timeout=120, env_extra={"KGB_NEO4J_PASSWORD": "test-only"})
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("neo4j.uri", result.stderr)
        result = run_kgb(["neo4j", "demo", "--run", "tests/fixtures"], timeout=120,
                         env_extra={"KGB_NEO4J_PASSWORD": "test-only"})
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
