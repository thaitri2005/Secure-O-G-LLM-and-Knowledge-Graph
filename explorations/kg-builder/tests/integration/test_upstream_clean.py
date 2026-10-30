"""Verify that imports, workers, and tests leave both upstream clones pristine."""
from __future__ import annotations

import shutil
import subprocess
import unittest

from helpers import PROJECT_ROOT


class UpstreamCleanTest(unittest.TestCase):
    def test_upstream_clean(self):
        git = shutil.which("git")
        if git is None:
            self.fail("git missing")
        for name in ("kg-gen", "edc", "hipporag", "autoschemakg", "graphjudge"):
            result = subprocess.run([git, "-C", str(PROJECT_ROOT / "third_party" / name), "status", "--porcelain", "--ignored"],
                                    cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "", name + ": " + result.stdout)


if __name__ == "__main__":
    unittest.main()
