"""Reproduce every v1 score and artifact with complete-byte publication digests."""
from __future__ import annotations

import unittest
import json
from helpers import PROJECT_ROOT, run_kgb
from kgbuilder.core.text import sha256_file


COMMANDS = [['eval', 'wells', '--config', 'configs/experiments/bsee_eval.yaml', '--run', 'runs/reference/bsee_text/test_subset_v1_base/bsee_text_test_subset_v1_base/A0', '--corpus', 'data/benchmarks/bsee_text/v1', '--labels', 'data/evaluation/bsee_text/v1/silver', '--rules', 'data/evaluation/bsee_text/v1/rules', '--gold', 'data/benchmarks/bsee_gold/v1', '--gold-config', 'configs/experiments/bsee_gold.yaml', '--out', 'runs/_test/gold_v1_reproduction/test_base_A0'], ['eval', 'wells', '--config', 'configs/experiments/bsee_eval.yaml', '--run', 'runs/reference/bsee_text/test_subset_v1_base/bsee_text_test_subset_v1_base/A4', '--corpus', 'data/benchmarks/bsee_text/v1', '--labels', 'data/evaluation/bsee_text/v1/silver', '--rules', 'data/evaluation/bsee_text/v1/rules', '--gold', 'data/benchmarks/bsee_gold/v1', '--gold-config', 'configs/experiments/bsee_gold.yaml', '--baseline', 'runs/_test/gold_v1_reproduction/test_base_A0', '--out', 'runs/_test/gold_v1_reproduction/test_base_A4'], ['eval', 'wells', '--config', 'configs/experiments/bsee_eval.yaml', '--run', 'runs/reference/bsee_text/test_subset_v1_guided/bsee_text_test_subset_v1_guided/A4', '--corpus', 'data/benchmarks/bsee_text/v1', '--labels', 'data/evaluation/bsee_text/v1/silver', '--rules', 'data/evaluation/bsee_text/v1/rules', '--gold', 'data/benchmarks/bsee_gold/v1', '--gold-config', 'configs/experiments/bsee_gold.yaml', '--baseline', 'runs/_test/gold_v1_reproduction/test_base_A4', '--out', 'runs/_test/gold_v1_reproduction/test_guided_A4'], ['eval', 'wells', '--config', 'configs/experiments/bsee_eval.yaml', '--corpus', 'data/benchmarks/bsee_text/v1', '--gold-config', 'configs/experiments/bsee_gold.yaml', '--split', 'dev', '--run', 'runs/reference/bsee_text/dev_v1_base/bsee_text_dev_v1_base/A4', '--labels', 'data/evaluation/bsee_text/v1/silver', '--rules', 'data/evaluation/bsee_text/v1/rules', '--gold', 'data/benchmarks/bsee_gold/v1', '--out', 'runs/_test/gold_v1_reproduction/dev_base_A4'], ['eval', 'wells', '--config', 'configs/experiments/bsee_eval.yaml', '--corpus', 'data/benchmarks/bsee_text/v1', '--gold-config', 'configs/experiments/bsee_gold.yaml', '--split', 'dev', '--run', 'runs/reference/bsee_text/dev_v1_guided/bsee_text_dev_v1_guided/A4', '--labels', 'data/evaluation/bsee_text/v1/silver', '--rules', 'data/evaluation/bsee_text/v1/rules', '--gold', 'data/benchmarks/bsee_gold/v1', '--out', 'runs/_test/gold_v1_reproduction/dev_guided_A4', '--baseline', 'runs/_test/gold_v1_reproduction/dev_base_A4'], ['eval', 'attribution', '--config', 'configs/experiments/bsee_eval.yaml', '--corpus', 'data/benchmarks/bsee_text/v1', '--gold-config', 'configs/experiments/bsee_gold.yaml', '--split', 'dev', '--run', 'runs/reference/bsee_text/dev_v1_guided/bsee_text_dev_v1_guided/A4', '--out', 'runs/_test/gold_v1_reproduction/dev_attribution'], ['eval', 'attribution', '--config', 'configs/experiments/bsee_eval.yaml', '--run', 'runs/reference/bsee_text/test_subset_v1_guided/bsee_text_test_subset_v1_guided/A4', '--corpus', 'data/benchmarks/bsee_text/v1', '--gold-config', 'configs/experiments/bsee_gold.yaml', '--split', 'test', '--out', 'runs/_test/gold_v1_reproduction/test_attribution']]


class BseeGoldV1ReproductionTest(unittest.TestCase):
    def test_reproduction(self):
        self.assertTrue((PROJECT_ROOT / "data/benchmarks/bsee_text/v1/selection.json").is_file())
        expected = json.loads((PROJECT_ROOT / "tests/fixtures/bsee_guided/published_artifact_sha256.json").read_text())
        checked = set()
        for command in COMMANDS:
            result = run_kgb([*command, "--overwrite"], timeout=180)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            output = PROJECT_ROOT / command[command.index("--out") + 1]
            for name, digest in expected.items():
                group, leaf = name.split("/")
                if group != output.name:
                    continue
                self.assertEqual(sha256_file(output / leaf), digest, name)
                checked.add(name)
        self.assertEqual(checked, set(expected))
