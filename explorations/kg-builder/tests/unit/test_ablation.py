"""Small synthetic ablation tables and in-process configuration checks."""
from __future__ import annotations

import copy
import json
import unittest
from unittest.mock import patch

import yaml

from helpers import PROJECT_ROOT, clean_dir
from kgbuilder.build import pipeline
from kgbuilder.core.config import ConfigError, PRESETS, AblationInduce, load_ablation
from kgbuilder.core.text import write_json, write_jsonl
from kgbuilder.evaluation import ablation as mod


class AblationTest(unittest.TestCase):
    def setUp(self):
        self.root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/ablation" / self._testMethodName)
        self.path = self.root / "ablation_sentence_grounding.yaml"
        self.body = {"name": "test", "levels": ["A0", "A4", "A5"], "runs": [{"config": "configs/experiments/showcase.yaml"}]}

    def config(self, body=None):
        self.path.write_text(yaml.safe_dump({"ablation": body or self.body}), encoding="utf-8")
        return load_ablation(self.path)

    def select(self, body=None, **kwargs):
        return pipeline.ablation_configs(self.config(body), mock=True, sets=kwargs.get("sets", []),
                                         only=kwargs.get("only", []), exclude=kwargs.get("exclude", []))

    def test_modules_and_new_calls(self):
        self.assertEqual(mod.modules(PRESETS["A0"]), "- - - - -")
        self.assertEqual(mod.modules(PRESETS["A4"]), "R C T V -")
        self.assertEqual(mod.modules(PRESETS["A5"]), "R C T V J")
        seen = set()
        def row(key, stage="extract", seconds=1):
            return {"key": key, "stage": stage, "seconds": seconds}
        self.assertEqual(mod.new_calls([row("k1"), row("k2")], seen, {})["new_calls"], 2)
        self.assertEqual(mod.new_calls([row("k1")], seen, {})["new_calls"], 0)
        self.assertEqual(mod.new_calls([row("k1"), row("k3", "canon", 0)], seen, {"k3": {"seconds": 7.5}}),
                         {"calls": 2, "new_calls": 1, "new_seconds": 7.5, "new_by_stage": {"canon": 1}})
        self.assertEqual(mod.new_calls([row("x", seconds=2), row("x", seconds=99)], set(), {})["new_seconds"], 2)

    def test_cross_field_checks(self):
        qa = {"config": "configs/experiments/showcase.yaml", "run": "showcase", "levels": ["A0"]}
        baseline = {"label": "test", "eval_txt": "results/upstream/edc/webnlg_10/eval.txt"}
        cases = [({**self.body, "qa": {**qa, "run": "nope"}}, "qa.run"),
                 ({**self.body, "qa": {**qa, "levels": ["A3"]}, "runs": [{**self.body["runs"][0], "levels": ["A0", "A4"]}]}, "qa.levels"),
                 ({**self.body, "levels": ["A0", "A4"], "runs": [{**self.body["runs"][0], "levels": ["A5"]}]}, "levels"),
                 ({**self.body, "baselines": {"nope": baseline}}, "baselines"),
                 ({**self.body, "runs": self.body["runs"] * 2}, "duplicate run.name")]
        for body, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ConfigError, message):
                self.select(body)
        for kwargs in [{"only": ["nope"]}, {"exclude": ["nope/A0"]}, {"exclude": ["showcase/A6"]},
                       {"exclude": ["showcase/A0", "showcase/A4", "showcase/A5"]}]:
            with self.assertRaises(ConfigError):
                self.select(**kwargs)
        selected = self.select(exclude=["showcase/A5"])
        self.assertEqual(selected[0][1:], (["A0", "A4"], ["A5"]))
        changed = self.select(sets=["run.name=changed", "flags.canon=false"], exclude=["changed/A5"])
        self.assertEqual(changed[0][0].run.name, "changed")
        body = {**self.body, "runs": [self.body["runs"][0], {**self.body["runs"][0], "sets": ["run.name=second", "llm.max_tokens=32"]}]}
        with self.assertRaisesRegex(ConfigError, "selected run llm sections differ"):
            self.select(body)
        self.assertEqual(len(self.select(body, only=["showcase"])), 1)

    def synthetic(self):
        level = self.root / "A4"
        metrics = {"entities": 4, "entities_literal": 1, "statements_accepted": 3, "statements_rejected": 1,
                   "rejected_by_reason": {"weak_evidence": 1}, "er_reduction": .2, "temporal_statements": 2,
                   "candidates": 10, "grounding": {"exact": 9, "partial": 1, "none": 0}, "stage_seconds": {"extract": .25, "canon": .1},
                   "canon": {"unmapped": 1}}
        write_json(level / "metrics.json", metrics)
        write_json(level / "graph.json", {"statements": [{"predicate": p} for p in ["works_at", "works at", "operates"]]})
        write_json(level / "eval/showcase_checks.json", {"status": {"G1": "PASS", "G2": "PASS", "G3": "PASS", "G4": dict.fromkeys(["q1", "q2", "q3", "q4"], "PASS"), "G5": "PASS", "G6": "FAIL", "gold_recall": .75}})
        write_jsonl(level / "llm_calls.jsonl", [{"key": "x", "stage": "judge", "seconds": 8}])
        write_jsonl(level / "judge.jsonl", [{"verdict": "yes", "error": None}, {"verdict": "no", "error": None}, {"verdict": None, "error": None}, {"verdict": None, "error": "broken"}])
        scores = {"strict": {"P": .8, "R": .9, "F1": .843}, "full_triple": {"F1": .465},
                  "per_tag": {tag: {"strict": {"F1": .9}} for tag in ("subjects", "predicates", "objects")}}
        write_json(level / "eval/scores.json", scores)
        row = mod.level_row("showcase", "A4", level, 0, set(), {})
        row["modules"] = mod.modules(PRESETS["A4"])
        failed = mod.level_row("showcase", "A5", self.root / "A5", 5, set(), {})
        failed["modules"] = mod.modules(PRESETS["A5"])
        skipped = mod.level_row("other", "A0", self.root / "missing", None, set(), {})
        skipped["modules"] = mod.modules(PRESETS["A0"])
        return {"format": mod.FORMAT, "name": "test", "levels": ["A0", "A4", "A5"], "mock": True,
                "rows": [row, failed, skipped], "baselines": {"webnlg10": {"label": "B-EDC", "webnlg": scores}}, "qa": None, "induce": []}

    def test_level_and_markdown(self):
        table = self.synthetic()
        row = table["rows"][0]
        self.assertEqual(row["grounding"], {"exact": .9, "partial": .1, "none": 0.0})
        self.assertEqual(row["predicate_redundancy"], .3333)
        self.assertEqual(row["showcase"], {"passed": 8, "total": 9, "failed": ["G6"], "gold_recall": .75})
        self.assertEqual(row["judge"], {"judged": 4, "yes": 1, "no": 1, "unparsed": 1, "errors": 1})
        self.assertEqual(row["webnlg"]["subject_F1"], .9)
        self.assertEqual(row["webnlg"]["full_triple_F1"], .465)
        rendered = mod.render_md(table)
        for value in ["8/9 (FAIL: G6)", "B-EDC", "0.900/0.100/0.000", "QA: not run (no qa block)", "Schema induction: not configured"]:
            self.assertIn(value, rendered)
        for value in ["build-stage entities", "build-stage literals", "ER reduction (build-stage)",
                      "accepted statements", "graph predicate types", "Populations:", "cumulative module changes"]:
            self.assertIn(value, rendered)
        for i in range(1, 7):
            self.assertIn(f"## {i}.", rendered)
        failed_lines = [line for line in rendered.splitlines() if line.startswith("| showcase | A5 |")]
        self.assertEqual([line.count("FAILED (exit 5)") for line in failed_lines], [9, 9, 5])
        skipped_lines = [line for line in rendered.splitlines() if line.startswith("| other | A0 |")]
        self.assertEqual([line.count("skipped (--exclude)") for line in skipped_lines], [9, 9, 5])
        mod.write(table, self.root)
        self.assertEqual(json.loads((self.root / "ablation.json").read_text()), table)

    def test_plan_note(self):
        table = self.synthetic()
        original = mod.render_md(table).splitlines()[:2]
        table["plan"] = False
        self.assertEqual(mod.render_md(table).splitlines()[:2], original)
        table["plan"] = True
        lines = mod.render_md(table).splitlines()
        self.assertEqual(lines[0], original[0])
        self.assertEqual(lines[1], original[1] + "; plan: true (counts only; judge/reader answers are empty)")

    def test_window_grounding_section(self):
        table = self.synthetic()
        self.assertIn("| showcase | A4 | \u2013 | \u2013 | \u2013 | \u2013 |", mod.render_md(table))
        table["rows"][0].update(flagged=2, flagged_by_reason={"weak_evidence": 2},
                               ground_rules={"exact": 3, "window": 4, "coref": 5}, webnlg_strict={"F1": .7})
        rendered = mod.render_md(table)
        self.assertIn("3/4/5/0/0/0", rendered)
        self.assertIn("0.700", rendered)

    def test_collect_and_summary_exclusions(self):
        table = self.synthetic()
        abl = self.config({**self.body, "runs": [{**self.body["runs"][0], "sets": ["run.name=changed", "flags.canon=false"], "levels": ["A4", "A5"]}]})
        selected = pipeline.ablation_configs(abl, True, [], [], ["changed/A5"])
        cfg = selected[0][0]
        result = pipeline.RunResult(self.root / "changed/A4", 5, {}, "miss")
        built = {"changed": {"A4": result, "A5": None}}
        collected = mod.collect(abl, self.root, built, None, {}, True, {})
        self.assertEqual([r["status"] for r in collected["rows"]], ["failed", "skipped"])
        self.assertEqual([r["modules"] for r in collected["rows"]], ["R - T V -", "R - T V J"])
        summary = pipeline._summary_run(cfg, abl.runs[0].config, ["A4", "A5"], built["changed"], {})
        self.assertEqual(list(summary["levels"]), ["A4"])
        with patch.object(pipeline, "run_levels", return_value={"A4": result}) as runner:
            actual = pipeline.ablate_builds(selected, self.root, object(), self.root / "net.jsonl")
        self.assertEqual(actual, built)
        self.assertEqual(runner.call_count, 1)

    def test_qa_and_induce_blocks(self):
        table = self.synthetic()
        path = self.root / "qa"
        rows = [{"row": name, "graph": graph, "em": .5, "f1": .75, "recall@2": .8, "recall@5": 1.0,
                 "no_context": 0, "seeded": None if graph is None else 1, "llm": {"calls": 1}}
                for name, graph in [("text", None), ("graph@A4", "A4"), ("hybrid@A4", "A4")]]
        write_json(path / "qa.json", {"rows": rows, "recall_k": [2, 5], "graphs": {"A4": {"statements": 3, "evidence_pair_recall": .5, "evidence_entity_recall": .75}}, "pairwise": []})
        write_jsonl(path / "llm_calls.jsonl", [{"key": key, "stage": "qa." + row["row"], "seconds": 0} for key, row in zip(["t", "g", "g"], rows)])
        qa = mod.qa_block(path, "2wiki10", ["A4"], {})
        self.assertEqual([r["new_calls"] for r in qa["rows"]], [1, 1, 0])
        self.assertEqual(qa["graphs"]["A4"]["statements"], 3)
        entry = AblationInduce(label="sample", induce_dir=self.root / "induce", pass2_run=self.root / "A4")
        self.assertEqual(mod.induce_block(entry)["status"], "not run")
        write_jsonl(self.root / "pass1/llm_calls.jsonl", [{"key": "x", "stage": "judge"}])
        write_json(entry.induce_dir / "summary.json", {"source_run": (self.root / "pass1").relative_to(PROJECT_ROOT).as_posix(),
                   "relations": {"open_types": 4, "canonical_types": 3, "induced_types": 2, "open_redundancy": .25, "induced_redundancy": 0.0},
                   "coverage": {"statements": .75, "entities_asked": 4, "entities_typed": 3}, "entity_types": {"person": 2, "organization": 2}, "llm": {"llm_calls": 4}})
        induced = mod.induce_block(entry)
        self.assertEqual(induced["top_types"], [["organization", 2], ["person", 2]])
        self.assertEqual(induced["pass2_new_calls"], 0)
        self.assertEqual(induced["pass2_unmapped"], 1)
        table.update(qa=qa, induce=[induced])
        rendered = mod.render_md(table)
        self.assertIn("graph@A4", rendered)
        self.assertIn("organization: 2, person: 2", rendered)

    def test_request_kind(self):
        cases = [({"stage": "extract"}, "extract"), ({"stage": "judge"}, "judge"),
                 ({"stage": "induce.concepts"}, "concept"), ({"stage": "qa.text"}, "qa"),
                 ({"stage": "canon", "messages": []}, "canon_other"), ({}, "other")]
        for marker, expected in [(mod.SD_MARK, "sd"), (mod.VERIFY_MARK, "verify")]:
            for role in ("system", "user"):
                cases.append(({"stage": "canon", "messages": [{"role": role, "content": "Please " + marker}]}, expected))
        for row, expected in cases:
            with self.subTest(row=row):
                self.assertEqual(mod.request_kind(row), expected)

    def test_pass2_incremental_accounting(self):
        table = self.synthetic()
        pass1 = self.root / "pass1"
        entry = AblationInduce(label="sample", induce_dir=self.root / "induce", pass2_run=self.root / "A4")
        def call(key, stage, marker="", hit=False):
            return {"key": key, "stage": stage, "messages": [{"role": "user", "content": marker}],
                    "cache_hit": hit, "seconds": 0 if hit else 1}
        first = [call("e1", "extract"), call("e2", "extract"), call("s1", "canon", mod.SD_MARK),
                 call("v1", "canon", mod.VERIFY_MARK)]
        second = [{**r, "cache_hit": True, "seconds": 0} for r in first[:3]] + [call("v2", "canon", mod.VERIFY_MARK)]
        summary = {"source_run": pass1.relative_to(PROJECT_ROOT).as_posix(),
                   "relations": {"open_types": 4, "canonical_types": 3, "induced_types": 2,
                                 "open_redundancy": .25, "induced_redundancy": 0.0},
                   "coverage": {"statements": .75, "entities_asked": 4, "entities_typed": 3},
                   "entity_types": {"person": 3}, "llm": {"llm_calls": 4}}
        write_json(entry.induce_dir / "summary.json", summary)
        write_jsonl(pass1 / "llm_calls.jsonl", first)
        write_jsonl(entry.pass2_run / "llm_calls.jsonl", second)
        row = mod.induce_block(entry)
        for key, value in {"pass2_calls": 4, "pass2_new_calls": 1, "pass2_new_by_kind": {"verify": 1},
                           "pass2_new_verify_calls": 1, "pass2_fresh_calls": 1, "pass1_log_missing": False}.items():
            self.assertEqual(row[key], value, key)
        self.assertEqual(mod.new_calls(second, set(), {})["new_calls"], 4)
        absent = mod.induce_block(AblationInduce(label="absent", induce_dir=self.root / "absent"))
        table["induce"] = [row, absent]
        rendered = mod.render_md(table)
        self.assertIn("pass-2 calls total / new vs pass 1 / new verify / fresh", rendered)
        self.assertIn("4 / 1 / 1 / 1", rendered)
        self.assertEqual(next(line for line in rendered.splitlines() if line.startswith("| absent |")).count("not run"), 13)
        summary["source_run"] = (self.root / "missing_pass1").relative_to(PROJECT_ROOT).as_posix()
        write_json(entry.induce_dir / "summary.json", summary)
        missing = mod.induce_block(entry)
        self.assertTrue(missing["pass1_log_missing"])
        self.assertEqual((missing["pass2_calls"], missing["pass2_fresh_calls"]), (4, 1))
        for key in ("pass2_new_calls", "pass2_new_by_kind", "pass2_new_verify_calls"):
            self.assertIsNone(missing[key], key)
        table["induce"] = [missing]
        self.assertIn("4 / \u2013 / \u2013 / 1", mod.render_md(table))
