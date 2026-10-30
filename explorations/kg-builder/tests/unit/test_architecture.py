"""Architecture and dependency guard tests for the package."""
from __future__ import annotations

import ast
import importlib.metadata
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "kgbuilder"
LAYERS = {"runtime": {"runtime", "core"}, "core": {"core"},
          "build": {"core", "runtime", "build"}, "evaluation": {"core", "runtime", "build.publish"},
          "serve": {"core", "serve"}, "adapters": {"core"}}


def import_targets(node: ast.AST) -> list[str] | None:
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    if isinstance(node, ast.ImportFrom):
        if node.level > 0: return ["<relative>"]
        if node.module == "kgbuilder":
            return ["kgbuilder" if a.name == "__version__" else "kgbuilder." + a.name for a in node.names]
        return [node.module] if node.module else []
    return None


def layer_violations(rel: tuple[str, ...], source: str) -> list[str]:
    allowed = LAYERS.get(rel[0]) if len(rel) > 1 else None
    if rel == ("build", "pipeline"): allowed = allowed | {"evaluation"}
    violations = []
    for node in ast.walk(ast.parse(source)):
        for target in import_targets(node) or []:
            if target == "<relative>":
                violations.append(target)
                continue
            if target != "kgbuilder" and not target.startswith("kgbuilder."): continue
            if rel[-1] == "__init__":
                violations.append(target)
                continue
            inner = target.partition(".")[2]
            if allowed is not None and inner and not any(inner == a or inner.startswith(a + ".") for a in allowed):
                violations.append(target)
    return violations


class ArchitectureTest(unittest.TestCase):
    def test_requirements_pinned_and_installed(self):
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"): continue
            self.assertRegex(line, r"^[A-Za-z0-9_.-]+==[^\s=]+$")
            name, version = line.strip().split("==", 1)
            self.assertEqual(importlib.metadata.version(name), version)

    def test_modules(self):
        stdlib = set(sys.stdlib_module_names)
        allowed = stdlib | {"yaml", "pydantic", "networkx", "numpy", "kgbuilder"}
        extras = {"kggen.py": {"kg_gen", "dspy", "sentence_transformers"}, "resolve.py": {"kg_gen", "dspy", "sentence_transformers", "semhash"}, "edc_worker.py": {"edc", "openai", "sentence_transformers"}, "route.py": {"sentence_transformers"}, "neo4j_store.py": {"neo4j"}, "neo4j_domain.py": {"neo4j"}, "qa.py": {"sentence_transformers"}}
        py39 = {"__init__.py", "project.py", "onprem.py", "gateway.py", "edc_worker.py", "choice.py"}
        for path in SRC.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            self.assertIsNotNone(ast.get_docstring(tree), path)
            self.assertIsInstance(tree.body[1], ast.ImportFrom, path)
            self.assertEqual(tree.body[1].module, "__future__", path)
            self.assertIn("annotations", [a.name for a in tree.body[1].names])
            if path.name in py39: ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 9))
            for n in ast.walk(tree):
                if isinstance(n, ast.ImportFrom): self.assertEqual(n.level, 0, path)
                if isinstance(n, ast.Import): names = [a.name.split(".")[0] for a in n.names]
                elif isinstance(n, ast.ImportFrom) and n.module: names = [n.module.split(".")[0]]
                else: continue
                for name in names:
                    self.assertTrue(name in allowed or name in extras.get(path.name, set()), f"{path}: {name}")
                    if path.name in py39:
                        if name == "kgbuilder":
                            self.assertIsInstance(n, ast.ImportFrom)
                            self.assertIn(n.module, {"kgbuilder.runtime.onprem", "kgbuilder.core.project", "kgbuilder.core.choice"})
                        elif name not in extras.get(path.name, set()):
                            self.assertIn(name, stdlib, f"Python 3.9 module imports {name}")
            if path.name in {"edc_worker.py", "route.py", "neo4j_store.py", "qa.py"}:
                for top in tree.body:
                    if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): continue
                    for n in ast.walk(top):
                        if isinstance(n, ast.Import): roots = [a.name.split(".")[0] for a in n.names]
                        elif isinstance(n, ast.ImportFrom): roots = [(n.module or "").split(".")[0]]
                        else: continue
                        self.assertFalse(set(roots) & extras[path.name], path)
            text = path.read_text(encoding="utf-8")
            if "third_party" in text: self.assertIn(path.name, {"config.py", "pipeline.py", "edc_worker.py", "evaluate.py"})

    def test_layers(self):
        for path in SRC.rglob("*.py"):
            rel = path.relative_to(SRC).with_suffix("").parts
            self.assertEqual(layer_violations(rel, path.read_text(encoding="utf-8")), [], str(path))

    def test_layer_checker_catches_bypasses(self):
        cases = [(("core", "text"), "from kgbuilder import build", 1),
                 (("core", "text"), "from .. import runtime", 1),
                 (("core", "text"), "from . import contracts", 1),
                 (("core", "text"), "from kgbuilder import __version__", 0),
                 (("core", "config"), "from kgbuilder.runtime.onprem import PROJECT_ROOT", 1),
                 (("runtime", "gateway"), "from kgbuilder.core.project import PROJECT_ROOT", 0),
                 (("build", "refine", "canon"), "import kgbuilder.evaluation.evaluate", 1),
                 (("build", "pipeline"), "from kgbuilder import evaluation", 0),
                 (("core", "__init__"), "from kgbuilder.core import text", 1),
                 (("serve", "query"), "from kgbuilder.core.text import match_key", 0),
                 (("serve", "qa"), "from kgbuilder.serve.query import load_graph", 0),
                 (("serve", "qa"), "from kgbuilder.runtime.gateway import Gateway", 1),
                 (("serve", "query"), "from kgbuilder.runtime.gateway import Gateway", 1),
                 (("serve", "qa"), "from kgbuilder.build.ingest.corpus import load_corpus", 1),
                 (("serve", "qa"), "import kgbuilder.evaluation.evaluate", 1),
                 (("serve", "qa"), "from kgbuilder.adapters import neo4j_store", 1),
                 (("serve", "query"), "from kgbuilder.build.publish import export", 1),
                 (("build", "pipeline"), "from kgbuilder.serve import query", 1),
                 (("evaluation", "evaluate"), "import kgbuilder.serve.query", 1),
                 (("adapters", "neo4j_store"), "from kgbuilder.core.text import match_key", 0),
                 (("adapters", "neo4j_store"), "from kgbuilder.serve import query", 1),
                 (("build", "pipeline"), "import kgbuilder.adapters.neo4j_store", 1)]
        for rel, source, count in cases:
            with self.subTest(source=source): self.assertEqual(len(layer_violations(rel, source + "\n")), count)


if __name__ == "__main__": unittest.main()
