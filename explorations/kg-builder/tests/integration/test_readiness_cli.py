"""Night-only CLI checks for stage readiness and preflight delegation."""
from __future__ import annotations

import json
import unittest

from helpers import PROJECT_ROOT, clean_dir, fake_lmstudio, replay_set, run_kgb

MODEL = "qwen3.6-35b-a3b"


class ReadinessCliTest(unittest.TestCase):
    def test_stage_rechecks_and_readonly_skips(self):
        root = clean_dir(PROJECT_ROOT / "runs/_test/readiness")
        for identity in ("readiness_a1", "readiness_mock"):
            clean_dir(PROJECT_ROOT / ".cache/tmp/tests" / identity)
        paths = []
        details = 0
        def meta(path):
            nonlocal details
            paths.append(path)
            if path == "/v1/models":
                return {"data": [{"id": MODEL}]}
            if path.startswith("/api/v0/models/"):
                details += 1
                return {"state": "loaded", "loaded_context_length": 8192 if details == 1 else 4096}
            return {}
        with fake_lmstudio(lambda b: "", metadata=meta) as (url, received):
            common = ["build", "--config", "configs/experiments/showcase.yaml", "--ablation", "A1",
                      "--set", "llm.base_url=" + url, "--set", "llm.cache=readwrite",
                      *replay_set(), "--overwrite"]
            result = run_kgb([*common, "--out", str(root / "A1")], test_id="readiness_a1", timeout=600)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertEqual(received, [])
            self.assertEqual(details, 2)
            self.assertIn("Build exit 3", result.stdout)
            self.assertEqual(json.loads((root / "A1/manifest.json").read_text())["exit_code"], 3)
            self.assertTrue((root / "A1/metrics.json").is_file())
            log = (root / "A1/run.log").read_text(encoding="utf-8")
            self.assertIn("model context is too small", log)
            self.assertIn("lms load", log)
            paths.clear()
            result = run_kgb([*common, "--mock", "--out", str(root / "mock")],
                             test_id="readiness_mock", timeout=600)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(paths, [])
            self.assertEqual(received, [])
        self.assertFalse((PROJECT_ROOT / ".cache/tmp/tests/readiness_mock/no_cache.jsonl").exists())

    def test_preflight_delegates_to_model_ready(self):
        def meta(detail):
            return lambda path: {"data": [{"id": MODEL}]} if path == "/v1/models" else detail
        with fake_lmstudio(lambda b: "", metadata=meta({})) as (url, received):
            result = run_kgb(["preflight", "--config", "configs/experiments/showcase.yaml",
                              "--set", "llm.base_url=" + url], timeout=600)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(result.stdout.rstrip().endswith("Preflight OK"))
            warning = "WARNING: không kiểm được context length"
            self.assertEqual(result.stderr.splitlines().count(warning), 1)
            if "WARNING: RAM trống < 3 GB" in result.stderr:
                self.assertLess(result.stderr.index(warning), result.stderr.index("WARNING: RAM trống < 3 GB"))
            self.assertEqual(received, [])
        with fake_lmstudio(lambda b: "", metadata=meta({"state": "loaded", "loaded_context_length": 4096})) as (url, received):
            result = run_kgb(["preflight", "--config", "configs/experiments/showcase.yaml",
                              "--set", "llm.base_url=" + url], timeout=600)
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn("lms load qwen3.6-35b-a3b -c 8192 --parallel 2 -y", result.stderr)
            self.assertEqual(received, [])

