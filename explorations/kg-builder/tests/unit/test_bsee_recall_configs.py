"""Validate pre-registered variant configs and exact immutable prompt texts."""
from __future__ import annotations

import copy
import re
import unittest

import yaml

from helpers import PROJECT_ROOT
from kgbuilder.core.text import sha256_file


class BseeRecallConfigsTest(unittest.TestCase):
    def test_test_winner_matches_dev(self):
        folder = PROJECT_ROOT / "configs/experiments"
        name = "bsee_text_test_v2_guided_recall"
        winner = yaml.safe_load((folder / (name + ".yaml")).read_text())
        expected = yaml.safe_load((folder / "bsee_text_dev_v2_guided_recall.yaml").read_text())
        expected["run"]["name"] = name
        expected["corpus"]["path"] = "data/benchmarks/bsee_text/v2/test_subset.jsonl"
        self.assertEqual(winner, expected)
        self.assertEqual(yaml.safe_load((folder / (name + "_demo.yaml")).read_text()),
            {"demo": {"name": name + "_demo", "levels": ["A0", "A4"], "runs": ["configs/experiments/" + name + ".yaml"]}})

    def test_ten_configs(self):
        folder = PROJECT_ROOT / "configs/experiments"
        base = yaml.safe_load((folder / "bsee_text_dev_v2_guided.yaml").read_text())
        variants = {'guided': {}, 'guided_windows': {'guided_mode': 'windows2'}, 'guided_groups': {'guided_mode': 'groups4', 'guided_prompt': 'configs/prompts/bsee_guided_groups.txt'}, 'guided_recall': {'guided_recall_prompt': 'configs/prompts/bsee_guided_recall.txt'}}
        for variant, extra in variants.items():
            name = "bsee_text_dev_v2_" + variant
            expected = copy.deepcopy(base)
            expected["run"]["name"] = name
            expected["extract"].update(extra)
            self.assertEqual(yaml.safe_load((folder / (name + ".yaml")).read_text()), expected)
            self.assertEqual(yaml.safe_load((folder / (name + "_demo.yaml")).read_text()),
                {"demo": {"name": name + "_demo", "levels": ["A0", "A4"], "runs": ["configs/experiments/" + name + ".yaml"]}})
        test = yaml.safe_load((folder / "bsee_text_test_v2_guided.yaml").read_text())
        expected = copy.deepcopy(base)
        expected["run"]["name"] = "bsee_text_test_v2_guided"
        expected["corpus"]["path"] = "data/benchmarks/bsee_text/v2/test_subset.jsonl"
        self.assertEqual(test, expected)

    def test_exact_prompts(self):
        root = PROJECT_ROOT / "configs/prompts"
        v1 = (root / "bsee_guided.txt").read_text(encoding="utf-8")
        groups = (root / "bsee_guided_groups.txt").read_bytes()
        recall = (root / "bsee_guided_recall.txt").read_bytes()
        old = "- Choose relation names exactly from the supplied list of 21 definitions. Do not invent relations."
        new = "- Choose relation names exactly from the supplied list, which holds only some of the 21 relations; extract the facts that fit a listed relation. Do not invent relations."
        self.assertEqual(groups, v1.replace(old, new).encode())
        self.assertEqual(sum(a != b for a, b in zip(v1.splitlines(), groups.decode().splitlines())), 1)
        self.assertEqual(sha256_file(root / "bsee_guided_recall.txt"), "b66429eec7c0c1eb4131bcebe56cc2508a41ef1363caab1804405cff159b4188")
        self.assertEqual(recall.decode().split("=== USER ===", 1)[1], v1.split("=== USER ===", 1)[1])
        for content in (groups, recall):
            self.assertNotIn(b"\r", content)
            self.assertFalse(content.startswith(b"\xef\xbb\xbf"))
            self.assertTrue(content.endswith(b"\n"))
            self.assertFalse(content.endswith(b"\n\n"))
        self.assertEqual(sha256_file(root / "bsee_guided.txt"), "304bf4bec7c56e35332f5f11998f577ed0ec13b8f3b05141c4bb190d0c86dcb5")
