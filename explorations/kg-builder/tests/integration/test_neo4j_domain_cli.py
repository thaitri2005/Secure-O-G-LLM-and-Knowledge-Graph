"""Domain CLI and PowerShell prechecks, never starting Docker or a database."""
from __future__ import annotations

import subprocess
import unittest

from helpers import PROJECT_ROOT, run_kgb
from unit.test_well_link import link_fixture


class Neo4jDomainCliTest(unittest.TestCase):
    def test_cli(self):
        root, run, tables, _ = link_fixture("bsee_domain_cli")
        result = run_kgb(["domain", "bulk", "--tables", str(tables), "--out", str(root / "bulk")])
        self.assertEqual(result.returncode, 0, result.stderr)
        result = run_kgb(["neo4j", "domain-audit", "--tables", str(tables), "--bulk", str(root / "bulk")], env_extra={"KGB_NEO4J_PASSWORD": ""})
        self.assertEqual(result.returncode, 2)
        self.assertIn("KGB_NEO4J_PASSWORD", result.stderr)
        script = "function docker { throw 'Docker sentinel: must not run' }\n& './scripts/bsee_neo4j_import.ps1' -Bundle 'runs/_test/bsee_domain_cli/bulk' -StoreDir '.neo4j' -Image 'neo4j:5.26.0-community'\nexit $LASTEXITCODE"
        result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], cwd=PROJECT_ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertNotIn("Docker sentinel", result.stderr)
        data = PROJECT_ROOT / ".neo4j/bsee/data"
        populated = data.exists() and any(data.iterdir())
        script = "$global:dockerReached = $false\nfunction docker { $global:dockerReached = $true; $global:LASTEXITCODE = 1 }\n& './scripts/bsee_neo4j_import.ps1' -Bundle 'runs/_test/bsee_domain_cli/bulk' -StoreDir '.neo4j/bsee' -Image 'neo4j:5.26.0-community'\n$importExit = $LASTEXITCODE\nif ($global:dockerReached) { Write-Output 'Docker stub reached' }\nexit $importExit"
        result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], cwd=PROJECT_ROOT, capture_output=True, text=True)
        if populated:
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("Store data must be absent or empty", result.stdout + result.stderr)
            self.assertNotIn("Docker stub reached", result.stdout + result.stderr)
        else:
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn("start Docker Desktop", result.stdout)
