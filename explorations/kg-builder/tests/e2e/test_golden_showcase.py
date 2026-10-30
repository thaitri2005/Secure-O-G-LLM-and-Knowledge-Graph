"""Full showcase golden acceptance using the live fixture captured in the evaluation contract."""
from __future__ import annotations

import json
import unittest

from helpers import PROJECT_ROOT, LIVE_FIXTURE, clean_dir, run_kgb
from kgbuilder.core.text import sha256_file


class GoldenShowcaseTest(unittest.TestCase):
    checks = None
    output = PROJECT_ROOT / "runs/_test/golden_showcase"

    def setUp(self):
        if not LIVE_FIXTURE.is_file():
            self.fail("Required recorded fixture is missing")
        if type(self).checks is None:
            clean_dir(self.output)
            self.build(self.output)
            result = run_kgb(["eval", "showcase", "--run", str(self.output)])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            type(self).checks = json.loads((self.output / "eval/showcase_checks.json").read_text(encoding="utf-8"))["status"]

    def build(self, out):
        result = run_kgb(["build", "--config", "configs/experiments/showcase.yaml", "--ablation", "A4",
                          "--mock", "--out", str(out), "--overwrite"], test_id="golden_showcase", timeout=900)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_required_golden_checks_and_determinism(self):
        for check in ["G1", "G3", "G5"]:
            self.assertEqual(self.checks[check], "PASS", check)
        self.assertEqual(self.checks["G4"]["q2"], "PASS")
        self.assertEqual(self.checks["G4"]["q3"], "PASS")
        other = PROJECT_ROOT / "runs/_test/golden_showcase_repeat"
        self.build(other)
        self.assertEqual(sha256_file(self.output / "graph.json"), sha256_file(other / "graph.json"))

    def test_g2_turing_two_supports(self):
        self.assertEqual(self.checks["G2"], "PASS")

    def test_g4_q1_born_in(self):
        self.assertEqual(self.checks["G4"]["q1"], "PASS")

    def test_g4_q4_works_on(self):
        self.assertEqual(self.checks["G4"]["q4"], "PASS")

    def test_g6_direction_a4_without_judge(self):
        self.assertEqual(self.checks["G6"], "FAIL")


if __name__ == "__main__":
    unittest.main()
