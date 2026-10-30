"""Synthetic table CLI dispatch, repeat hashes and output boundaries."""
from __future__ import annotations

import unittest

import yaml

from helpers import PROJECT_ROOT, clean_dir, run_kgb
from kgbuilder.core.domain import verify_bundle
from unit.test_bsee_tables import table_fixture


class BseeTablesCliTest(unittest.TestCase):
    def test_cli(self):
        root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/bsee_tables_cli")
        cfg = table_fixture(root)
        source = root / "tables.yaml"
        source.write_text(yaml.safe_dump(cfg.model_dump(mode="json")), encoding="utf-8")
        out = clean_dir(PROJECT_ROOT / "runs/_test/bsee_tables_cli")
        args = ["domain", "tables", "--config", str(source), "--out", str(out)]
        result = run_kgb(args)
        self.assertEqual(result.returncode, 0, result.stderr)
        before = verify_bundle(out).files
        self.assertEqual(run_kgb(args).returncode, 2)
        self.assertEqual(run_kgb(args + ["--overwrite"]).returncode, 0)
        self.assertEqual(verify_bundle(out).files, before)
        self.assertEqual(run_kgb(args[:-1] + [str(PROJECT_ROOT / "tests/fixtures")]).returncode, 2)
