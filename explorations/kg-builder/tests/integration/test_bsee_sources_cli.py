"""Offline registration CLI dispatch and failure-before-write checks."""
from __future__ import annotations

import json
import unittest

import yaml

from helpers import PROJECT_ROOT, clean_dir, run_kgb
from unit.test_bsee_sources import source_fixture


class BseeSourcesCliTest(unittest.TestCase):
    def test_registration_and_errors(self):
        root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/bsee_sources_cli")
        incoming, cfg, receipt = source_fixture(root)
        snapshot = "synthetic_bsee_cli"
        body = cfg.model_dump()
        body["snapshot"] = snapshot
        receipt["snapshot"] = snapshot
        (incoming / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
        output = clean_dir(PROJECT_ROOT / ".cache/datasets/bsee" / snapshot) / "manifest.json"
        path = root / "sources.yaml"
        path.write_text(yaml.safe_dump(body), encoding="utf-8")
        args = ["fetch", "bsee", "--config", str(path), "--from-dir", str(incoming)]
        result = run_kgb(args)
        self.assertEqual(result.returncode, 0, result.stderr)
        before = output.read_bytes()
        again = run_kgb(args)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(output.read_bytes(), before)
        self.assertEqual(again.stdout, result.stdout)
        receipt["files"][0]["sha256"] = "0" * 64
        (incoming / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
        result = run_kgb(args)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(output.read_bytes(), before)
        self.assertEqual(run_kgb(args + ["--url", "https://invalid.invalid"]).returncode, 2)
