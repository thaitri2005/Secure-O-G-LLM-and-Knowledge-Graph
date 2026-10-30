"""ZIP packaging acceptance, excluded content, and output containment."""
from __future__ import annotations

import re
import shutil
import subprocess
import unittest
import zipfile

from helpers import PROJECT_ROOT, clean_dir


class PackageTest(unittest.TestCase):
    def setUp(self):
        self.output = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/pkg")

    def package(self, *args):
        return subprocess.run([
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(PROJECT_ROOT / "scripts/package.ps1"), *args,
        ], cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=900)

    def test_selected_sources_and_exclusions(self):
        result = self.package("-OutDir", ".cache/tmp/tests/pkg")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        archives = list(self.output.glob("*.zip"))
        self.assertEqual(len(archives), 1)
        with zipfile.ZipFile(archives[0]) as archive:
            names = [name.replace("\\", "/") for name in archive.namelist()]
        for name in ["LICENSE", "src/kgbuilder/__init__.py", "results/expected_results.json",
                     "data/benchmarks/bsee_gold/v1/adjudicated.jsonl",
                     "data/benchmarks/bsee_gold/v2/adjudicated.jsonl",
                     "data/fixtures/llm/bsee_text_test_v2_guided.jsonl", ".env.example", ".gitignore"]:
            self.assertIn(name, names)
        forbidden = re.compile(r"(^|/)(\.git|\.venvs|\.venv|\.cache|\.neo4j|dist|runs|third_party|__pycache__|\.vscode|\.agents)(/|$)|^research/|(^|/)\.env$")
        self.assertEqual([name for name in names if forbidden.search(name)], [])

    def test_output_outside_project_rejected(self):
        result = self.package("-OutDir", r"C:\Windows\Temp\x")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_unknown_repository_rejected(self):
        result = self.package("-OutDir", ".cache/tmp/tests/pkg", "-ThirdParty", "unknown-repo")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(list(self.output.glob("*.zip")), [])

    def test_excluded_directories_are_never_enumerated(self):
        root = clean_dir(PROJECT_ROOT / "runs/_test/package_pruning")
        script = root / "probe.ps1"
        script.write_text(r"""$ErrorActionPreference = 'Stop'
$source = Join-Path (Get-Location) 'scripts/package.ps1'
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Package script syntax error' }
$function = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-PackageFiles' }, $true)
if (-not $function) { throw 'Pruning function missing' }
Invoke-Expression $function.Extent.Text
$assignment = $ast.Find({ param($node) $node -is [Management.Automation.Language.AssignmentStatementAst] -and $node.Left.Extent.Text -eq '$exclude' }, $true)
Invoke-Expression $assignment.Extent.Text
$Project = 'D:/synthetic'
$script:visited = [Collections.Generic.List[string]]::new()
function Get-ChildItem {
    param([string]$LiteralPath, [switch]$Force)
    $script:visited.Add($LiteralPath)
    switch ($LiteralPath) {
        'D:/synthetic/data' {
            [pscustomobject]@{FullName='D:/synthetic/data/benchmarks';PSIsContainer=$true}
            [pscustomobject]@{FullName='D:/synthetic/data/keep.json';PSIsContainer=$false}
        }
        'D:/synthetic/data/benchmarks' {
            [pscustomobject]@{FullName='D:/synthetic/data/benchmarks/.cache';PSIsContainer=$true}
            [pscustomobject]@{FullName='D:/synthetic/data/benchmarks/kept.json';PSIsContainer=$false}
        }
        default { throw 'Excluded subtree enumerated' }
    }
}
$files = @(Get-PackageFiles -Path 'D:/synthetic/data')
if ($script:visited.Count -ne 2) { throw 'Unexpected directory traversal' }
if (($files.FullName -join ',') -ne 'D:/synthetic/data/benchmarks/kept.json,D:/synthetic/data/keep.json') { throw 'Retained membership differs' }
Write-Output 'pruning OK; excluded directories enumerated 0'
""", encoding="utf-8")
        result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                                cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("excluded directories enumerated 0", result.stdout)

    def test_publication_exclusion_pattern(self):
        source = (PROJECT_ROOT / "scripts/package.ps1").read_text(encoding="utf-8")
        pattern = re.search(r"^\$exclude = '([^']+)'", source, re.M).group(1)
        for path in ("third_party/edc/source.py", ".venvs/python.exe", ".cache/model", "runs/reference/graph.json",
                     "research/papers/paper.pdf", ".env", ".env.local", "src/__pycache__/cached.pyc"):
            self.assertRegex(path, pattern)
        for path in ("data/benchmarks/bsee_gold/v1/adjudicated.jsonl", ".env.example",
                     "data/fixtures/llm/bsee_text_test_v2_guided.jsonl", "results/expected_results.json"):
            self.assertNotRegex(path, pattern)


if __name__ == "__main__":
    unittest.main()
