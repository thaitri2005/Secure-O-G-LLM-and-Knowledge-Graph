"""Offline demo summaries, selector validation, shared gateway, and fixtures."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from helpers import PROJECT_ROOT, METRIC_KEYS, clean_dir, run_kgb
from kgbuilder.core.config import ConfigError, from_resolved, load_config, load_demo
from kgbuilder.build.pipeline import RunResult, export_fixtures, run_demo, run_levels
from kgbuilder.core.text import read_jsonl, sha256_file, write_jsonl


class DemoTest(unittest.TestCase):
    def setUp(self):
        self.root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/demo" / self._testMethodName)

    @classmethod
    def setUpClass(cls):
        cls.out = clean_dir(PROJECT_ROOT / "runs/_test/demo")
        cls.result = run_kgb(["run", "--config", "configs/experiments/demo.yaml", "--mock", "--only", "showcase",
                              "--set", "flags.canon=false", "--out", str(cls.out), "--overwrite"],
                             test_id="demo", timeout=900)

    def test_demo_summary_offline_ladder(self):
        self.assertEqual(self.result.returncode, 0, self.result.stdout + self.result.stderr)
        summary = json.loads((self.out / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["format"], "kgb.demo/1")
        self.assertIs(summary["mock"], True)
        run = summary["runs"][0]
        self.assertEqual(run["name"], "showcase")
        self.assertEqual(run["config"], "configs/experiments/showcase.yaml")
        self.assertIsNone(run["baseline"])
        self.assertEqual(set(run["levels"]), {"A0", "A4"})
        for level in ["A0", "A4"]:
            value = run["levels"][level]
            self.assertEqual(set(value), {"exit_code", "run_dir", "metrics", "showcase", "webnlg", "extract"})
            self.assertEqual(value["extract"]["backend"], "kggen")
            self.assertEqual(len(value["extract"]["routes"]), 3)
            self.assertEqual(set(value["metrics"]), METRIC_KEYS)
            self.assertIsNone(value["webnlg"])
        self.assertEqual(run["levels"]["A0"]["showcase"]["G1"], "FAIL")
        self.assertEqual(run["levels"]["A0"]["showcase"]["G3"], "FAIL")
        self.assertEqual(run["levels"]["A0"]["showcase"]["gold_recall"], 0.0)
        checks = run["levels"]["A4"]["showcase"]
        for check in ["G1", "G3", "G5"]:
            self.assertEqual(checks[check], "PASS")
        self.assertEqual(checks["G4"]["q2"], "PASS")
        self.assertEqual(checks["G4"]["q3"], "PASS")
        calls = read_jsonl(self.out / "showcase/A4/llm_calls.jsonl")
        self.assertEqual(run["levels"]["A4"]["metrics"]["llm"]["calls"], len(calls))
        self.assertNotRegex((self.out / "report.html").read_text(encoding="utf-8"), r"https?://")

    def test_selector_preserves_output(self):
        output = PROJECT_ROOT / "runs/_test/demo_bad"
        if output.exists():
            clean_dir(output).rmdir()
        result = run_kgb(["run", "--config", "configs/experiments/demo.yaml", "--mock", "--only", "nope",
                          "--out", str(output), "--overwrite"])
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("showcase", result.stderr)
        self.assertIn("webnlg10", result.stderr)
        self.assertFalse(output.exists())

    def test_different_llm_sections(self):
        demo = load_demo(PROJECT_ROOT / "configs/experiments/demo.yaml")
        first = load_config(demo.runs[0], mock=True)
        data = first.model_dump(mode="json")
        data["llm"]["max_tokens"] = 4096
        second = from_resolved(data)
        output = PROJECT_ROOT / "runs/_test/demo_different_llm"
        with patch("kgbuilder.build.pipeline.load_config", side_effect=[first, second]):
            with self.assertRaises(ConfigError) as cm:
                run_demo(demo, mock=True, sets=[], only=None, out_root=output, net_core_log=self.root / "net.jsonl")
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("llm.max_tokens", str(cm.exception))

    def test_fixture_cli_and_overwrite(self):
        self.assertEqual(self.result.returncode, 0, self.result.stdout + self.result.stderr)
        dst = self.root / "fixture.jsonl"
        command = ["fixtures", "--from", str(self.out), "--to", str(dst)]
        result = run_kgb(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        unique = {r["key"] for path in self.out.rglob("llm_calls.jsonl") for r in read_jsonl(path) if r.get("content") is not None}
        self.assertEqual(len(read_jsonl(dst)), len(unique))
        first = sha256_file(dst)
        self.assertEqual(run_kgb(command).returncode, 2)
        self.assertEqual(sha256_file(dst), first)
        self.assertEqual(run_kgb(command + ["--overwrite"]).returncode, 0)
        empty = clean_dir(self.root / "empty")
        self.assertEqual(run_kgb(["fixtures", "--from", str(empty), "--to", str(self.root / "empty.jsonl")]).returncode, 2)
        self.assertFalse((self.root / "empty.jsonl").exists())

    def test_sticky_fatal_fails_fast(self):
        cfg = load_config(PROJECT_ROOT / "configs/experiments/showcase.yaml", mock=True)
        class Fatal:
            fatal = "cache_miss:sticky"
        with patch("kgbuilder.build.pipeline.build") as mocked:
            result = run_levels(cfg, ["A0", "A4"], PROJECT_ROOT / "runs/_test/sticky", Fatal(), self.root / "net.jsonl")
        self.assertEqual([r.exit_code for r in result.values()], [5, 5])
        mocked.assert_not_called()


if __name__ == "__main__":
    unittest.main()
