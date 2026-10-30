"""Synthetic rule CLI determinism; the protocol guard is added in the evaluation contract."""
from __future__ import annotations

import unittest

from helpers import run_kgb
from unit.test_well_eval import eval_fixture
from unit.test_well_gold import TEST_CONFIG, gold_fixture


class WellRulesCliTest(unittest.TestCase):
    def test_cli(self):
        root, _, _, corpus = eval_fixture("bsee_rules_cli")
        cfg = gold_fixture(complete=True)
        for name in ("rules", "repeat"):
            result = run_kgb(["domain", "rules", "--gold-config", str(TEST_CONFIG), "--corpus", str(corpus), "--out", str(root / name)])
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((root / "rules/rules.jsonl").read_bytes(), (root / "repeat/rules.jsonl").read_bytes())
        import json
        self.assertEqual({json.loads(line)["annotator"] for line in (root / "rules/rules.jsonl").read_text().splitlines()}, {"rules/v2"})
        result = run_kgb(["domain", "rules", "--corpus", str(corpus), "--out", str(root / "bad")])
        self.assertEqual(result.returncode, 2)
        path = cfg["root"] / "freeze.json"
        freeze = json.loads(path.read_text()); freeze["frozen_inputs"]["src/kgbuilder/evaluation/well_rules.py"] = "0" * 64
        path.write_text(json.dumps(freeze), encoding="utf-8")
        result = run_kgb(["domain", "rules", "--gold-config", str(TEST_CONFIG), "--corpus", str(corpus), "--out", str(root / "bad")])
        self.assertEqual(result.returncode, 2)
        self.assertFalse((root / "bad").exists())
