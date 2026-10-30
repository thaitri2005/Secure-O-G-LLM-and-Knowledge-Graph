"""Check the config alias through fresh interpreter and CLI processes."""
from __future__ import annotations

import os
import subprocess
import unittest

from helpers import PROJECT_ROOT, PY_CORE, run_kgb


class NoWarningsTest(unittest.TestCase):
    def test_import(self):
        result = subprocess.run([str(PY_CORE), "-W", "error::UserWarning", "-c",
                                 "import kgbuilder.core.config"],
                                env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src"),
                                     "PYTHONDONTWRITEBYTECODE": "1"},
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli(self):
        result = run_kgb(["query", "--run", "tests/fixtures", "alias", "IBM"])
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertNotIn("shadows an attribute", result.stderr)
