"""Link CLI validates containment and uses synthetic verified outputs only."""
from __future__ import annotations

import unittest

from helpers import run_kgb
from unit.test_well_link import link_fixture


class WellLinkCliTest(unittest.TestCase):
    def test_cli(self):
        root, run, tables, sources = link_fixture("bsee_link_cli")
        flags = ["--policy", "configs/runtime/bsee_linking.yaml", "--out", str(root / "links")]
        result = run_kgb(["domain", "link", "--run", str(run), "--tables", str(tables), "--sources", str(sources), *flags])
        self.assertEqual(result.returncode, 0, result.stderr)
        result = run_kgb(["domain", "link", "--run", "tests/fixtures/bsee", "--tables", "tests/fixtures/bsee",
                          "--sources", "tests/fixtures/bsee/doc_sources.jsonl", *flags])
        self.assertEqual(result.returncode, 2)
