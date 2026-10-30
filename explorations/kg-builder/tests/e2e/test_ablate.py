"""Whole ablation command, fake A5 judge, exclusions, and recorded H1/H3 rows."""
from __future__ import annotations

import copy
import json
import unittest

import yaml

from helpers import PROJECT_ROOT, SENTENCE_GROUNDING, sets, TWOWIKI_QA_FIXTURE, clean_dir, fake_lmstudio, replay_set, run_kgb
from kgbuilder.core.text import read_jsonl


class AblateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/ablate" / self._testMethodName)
        self.root = clean_dir(PROJECT_ROOT / "runs/_test/ablate" / self._testMethodName)
        self.source = self.tmp / "ablation_sentence_grounding.yaml"
        self.body = {"name": "ablate_test", "levels": [f"A{i}" for i in range(6)],
                     "runs": [{"config": "configs/experiments/showcase.yaml", "sets": ["flags.canon=false"]}]}
        self.source.write_text(yaml.safe_dump({"ablation": self.body}), encoding="utf-8")

    def run_ablate(self, identity, flags, expected=0, source=None, out=None):
        cache = clean_dir(PROJECT_ROOT / ".cache/tmp/tests" / identity) / "no_cache.jsonl"
        output = out or self.root / identity
        result = run_kgb(["ablate", "--config", str(source or self.source), "--out", str(output), "--overwrite", *sets(SENTENCE_GROUNDING), *replay_set(), *flags],
                         test_id=identity, timeout=1800)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        if "--mock" in flags:
            self.assertFalse(cache.exists())
        return output, result

    def table(self, path):
        return json.loads((path / "ablation.json").read_text(encoding="utf-8"))

    def assert_no_misses(self, path):
        for metrics in path.rglob("metrics.json"):
            self.assertEqual(json.loads(metrics.read_text())["llm"]["cache_misses"], 0, str(metrics))
        for log in path.rglob("llm_calls.jsonl"):
            self.assertFalse(any(r.get("miss") for r in read_jsonl(log)), str(log))

    def test_live_mock_and_exclude(self):
        with fake_lmstudio(lambda _: "Yes, this is true.") as (url, received):
            out, _ = self.run_ablate("ablate_live", ["--set", "llm.base_url=" + url, "--set", "llm.cache=readwrite"])
        table = self.table(out)
        self.assertEqual([r["status"] for r in table["rows"]], ["ok"] * 6)
        prompts = {r["prompt"] for r in read_jsonl(out / "showcase/A5/judge.jsonl")}
        self.assertEqual(len(received), len(prompts))
        self.assertLessEqual(len(prompts), table["rows"][4]["statements"])
        self.assertTrue(all("Is this true:" in body["prompt"] for _, body in received))
        self.assertEqual(table["rows"][5]["llm"]["new_calls"], len(prompts))
        self.assertEqual([r["llm"]["new_calls"] for r in table["rows"][1:5]], [0] * 4)
        self.assertEqual(len(json.loads((out / "summary.json").read_text())["runs"][0]["levels"]), 6)
        self.assertNotIn("http", (out / "report.html").read_text(encoding="utf-8"))
        out, _ = self.run_ablate("ablate_mock", ["--mock"], 5)
        self.assertEqual([r["status"] for r in self.table(out)["rows"]], ["ok"] * 5 + ["failed"])
        self.assertIn("FAILED (exit 5)", (out / "ablation.md").read_text(encoding="utf-8"))
        out, _ = self.run_ablate("ablate_exclude", ["--mock", "--exclude", "showcase/A5"])
        self.assertEqual(self.table(out)["rows"][-1]["status"], "skipped")
        self.assertEqual(set(json.loads((out / "summary.json").read_text())["runs"][0]["levels"]), {f"A{i}" for i in range(5)})
        self.assertNotIn("http", (out / "report.html").read_text(encoding="utf-8"))
        self.assert_no_misses(out)

    def test_errors_before_writes(self):
        for flags in [["--exclude", "nope/A1"], ["--exclude", "showcase/A9"], ["--only", "nope"]]:
            out, _ = self.run_ablate("ablate_errors", ["--mock", *flags], 2)
            self.assertFalse(out.exists())
        _, _ = self.run_ablate("ablate_errors", ["--mock"], 2, out=PROJECT_ROOT / "tests/fixtures")
        for name, body in [("duplicate", {**self.body, "runs": self.body["runs"] * 2}),
                           ("qa", {**self.body, "qa": {"config": "configs/experiments/showcase.yaml", "run": "nope", "levels": ["A0"]}})]:
            source = self.tmp / (name + ".yaml")
            source.write_text(yaml.safe_dump({"ablation": body}), encoding="utf-8")
            out, result = self.run_ablate("ablate_errors", ["--mock"], 2, source=source)
            self.assertFalse(out.exists())
            if name == "qa":
                self.assertIn("qa.run", result.stderr)

    def test_webnlg_recorded(self):
        out, _ = self.run_ablate("ablate_webnlg", ["--mock", "--only", "webnlg10", "--only", "webnlg10_kggen",
                             "--only", "webnlg10_auto", "--exclude", "webnlg10/A5"], source=PROJECT_ROOT / "configs/experiments/ablation_sentence_grounding.yaml")
        table = self.table(out)
        self.assertEqual(len(table["rows"]), 16)
        skipped = [r for r in table["rows"] if r["status"] == "skipped"]
        self.assertEqual([(r["run"], r["level"]) for r in skipped], [("webnlg10", "A5")])
        self.assertIsNone(skipped[0]["exit_code"])
        for key, value in skipped[0].items():
            if key not in {"run", "level", "modules", "status", "exit_code"}:
                self.assertIsNone(value, key)
        self.assertTrue(all(r["status"] == "ok" for r in table["rows"]
                            if (r["run"], r["level"]) != ("webnlg10", "A5")))
        md = (out / "ablation.md").read_text(encoding="utf-8")
        excluded_lines = [line for line in md.splitlines() if line.startswith("| webnlg10 | A5 |")]
        self.assertEqual(len(excluded_lines), 3)
        self.assertTrue(all("skipped (--exclude)" in line for line in excluded_lines))
        summary = json.loads((out / "summary.json").read_text())
        webnlg = next(r for r in summary["runs"] if r["name"] == "webnlg10")
        self.assertNotIn("A5", webnlg["levels"])
        rows = {(r["run"], r["level"]): r for r in table["rows"]}
        for run, reference in [("webnlg10_kggen", "runs/reference/baseline_kggen/webnlg10/A4/eval/scores.json"),
                               ("webnlg10", "runs/reference/baseline_edc_router/webnlg10/A4/eval/scores.json")]:
            self.assertEqual(rows[run, "A4"]["webnlg"]["F1"], json.loads((PROJECT_ROOT / reference).read_text())["strict"]["F1"])
        for level in ("A1", "A3", "A4"):
            self.assertEqual(rows["webnlg10_kggen", level]["llm"]["new_calls"], 0)
        self.assertGreater(rows["webnlg10_kggen", "A2"]["llm"]["new_calls"], 0)
        self.assert_no_misses(out)

    def test_2wiki_recorded(self):
        if not TWOWIKI_QA_FIXTURE.is_file():
            self.fail("Required published test input is missing")
        out, _ = self.run_ablate("ablate_2wiki", ["--mock", "--only", "2wiki10", "--exclude", "2wiki10/A5",
                             *replay_set("data/fixtures/llm/twowiki10_kggen_qa.jsonl")], source=PROJECT_ROOT / "configs/experiments/ablation_sentence_grounding.yaml")
        rows = self.table(out)["qa"]["rows"]
        self.assertEqual([r["row"] for r in rows], ["text", "graph@A0", "graph@A1", "graph@A4", "hybrid@A0", "hybrid@A1", "hybrid@A4"])
        self.assert_no_misses(out)
        reference = PROJECT_ROOT / "runs/reference/twowiki10_sentence_grounding/qa/qa.json"
        if reference.is_file():
            recorded = {r["row"]: r for r in json.loads(reference.read_text())["rows"]}
            for row in rows:
                for key in ["em", "f1", "no_context", *[k for k in row if k.startswith("recall@")]]:
                    self.assertEqual(row[key], recorded[row["row"]][key])
