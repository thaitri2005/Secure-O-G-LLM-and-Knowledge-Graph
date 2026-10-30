"""Recorded evaluator scores, timeout behavior, and golden showcase checks."""
from __future__ import annotations

import json
import ast
import subprocess
import time
import unittest
from unittest.mock import patch

from helpers import PROJECT_ROOT, PY_EDC, clean_dir
from kgbuilder.core.config import KgbError, from_resolved, load_config
from kgbuilder.core.contracts import Entity, GraphRecord, ValidatedStatement, dump
from kgbuilder.evaluation.evaluate import (eval_showcase, eval_webnlg, parse_eval_txt,
                                permutation_report, run_webnlg_evaluator)
from kgbuilder.build.publish.export import graph_record, write_contract_files, write_graph_json
from kgbuilder.runtime.onprem import blocked_count
from kgbuilder.core.text import read_jsonl, write_json, write_jsonl


class EvaluateTest(unittest.TestCase):
    def setUp(self):
        self.root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/evaluate" / self._testMethodName)
        self.record = GraphRecord.model_validate_json((PROJECT_ROOT / "tests/fixtures/graph_small.json").read_text(encoding="utf-8"))
        self.recorded = PROJECT_ROOT / "results/upstream/edc/webnlg_10"
        self.cfg = load_config(PROJECT_ROOT / "configs/experiments/showcase.yaml", mock=True)

    def test_parse_recorded(self):
        scores = parse_eval_txt((self.recorded / "eval.txt").read_text(encoding="utf-8"))
        self.assertAlmostEqual(scores["strict"]["F1"], .843, delta=.001)
        self.assertAlmostEqual(scores["full_triple"]["F1"], .465, delta=.001)
        self.assertEqual(set(scores), {"ent_type", "partial", "strict", "exact", "per_tag", "full_triple"})
        self.assertEqual(set(scores["per_tag"]), {"subjects", "predicates", "objects"})
        self.assertEqual(set(scores["per_tag"]["subjects"]), {"strict", "exact"})
        self.assertAlmostEqual(scores["per_tag"]["subjects"]["strict"]["F1"], .914285714)
        with self.assertRaises(KgbError):
            parse_eval_txt("Strict\nF1: 1.0")

    def test_recorded_worker(self):
        started = time.monotonic()
        scores = run_webnlg_evaluator(self.recorded / "iter0/canon_kg.txt",
                                      self.recorded / "reference.txt", self.root, PY_EDC)
        write_json(self.root / "timing.json", {"evaluator_seconds": round(time.monotonic() - started, 1)})
        self.assertAlmostEqual(scores["strict"]["F1"], .843, delta=.001)
        self.assertAlmostEqual(scores["full_triple"]["F1"], .465, delta=.001)
        self.assertEqual(blocked_count(self.root / "net_eval.jsonl"), 0)
        self.assertTrue((self.root / "evaluator.log").exists())

    def test_timeout(self):
        # The recorded ten-document evaluator completes in less than a second
        # on this host; duplicate predictions to exercise its permutation cost.
        pred = self.root / "many_predictions.txt"
        lines = (self.recorded / "iter0/canon_kg.txt").read_text(encoding="utf-8").splitlines()
        pred.write_text("\n".join(str(ast.literal_eval(line) * 20) for line in lines) + "\n", encoding="utf-8")
        with self.assertRaises(KgbError) as cm:
            run_webnlg_evaluator(pred,
                                self.recorded / "reference.txt", self.root, PY_EDC, timeout_s=1)
        self.assertEqual(cm.exception.code, 6)
        self.assertIn("timeout", str(cm.exception))

    def test_worker_error_and_blocked_log(self):
        completed = subprocess.CompletedProcess([], 1, "", "\n".join(str(i) for i in range(50)))
        with patch("kgbuilder.evaluation.evaluate.subprocess.run", return_value=completed):
            with self.assertRaises(KgbError) as cm:
                run_webnlg_evaluator(self.recorded / "iter0/canon_kg.txt",
                                    self.recorded / "reference.txt", self.root, PY_EDC)
        self.assertEqual(cm.exception.code, 6)
        self.assertIn("\n10\n", str(cm.exception))
        self.assertNotIn("\n9\n", str(cm.exception))
        write_jsonl(self.root / "net_eval.jsonl", [{"allowed": False}])
        with patch("kgbuilder.evaluation.evaluate.subprocess.run", return_value=completed):
            with self.assertRaises(KgbError) as cm:
                run_webnlg_evaluator(self.recorded / "iter0/canon_kg.txt",
                                    self.recorded / "reference.txt", self.root, PY_EDC)
        self.assertEqual(cm.exception.code, 4)

    def test_permutations(self):
        rows = permutation_report([str([["s", "p", "o"]] * 12)], [str([["s", "p", "o"]] * 6)])
        self.assertEqual(rows, [{"doc": 0, "n_pred": 12, "n_gold": 6, "perm": 665280}])

    def golden(self):
        r = self.record
        base = r.statements[0]
        extra = [Entity(entity_id=eid, name=name, aliases=aliases, kind="entity", mention_ids=[], resolver="identity")
                 for eid, name, aliases in [("e5", "Alan Turing", ["Turing"]), ("e6", "London", []),
                                             ("e7", "IBM Research", []), ("e8", "artificial intelligence", [])]]
        entities = [*r.entities[:3], r.entities[3].model_copy(update={"aliases": [
            "International Business Machines", "International Business Machines Corporation"]}), *extra]
        e2 = r.statements[2].evidence_span
        # Two distinct, exact spans support the same golden birth statement.
        turing = base.model_copy(update={"statement_id": "s4", "subject_id": "e5", "object_id": "e6",
                                         "predicate": "born_in", "valid_from": None, "valid_to": None,
                                         "evidence": [base.evidence_span, e2], "support_count": 2,
                                         "candidate_ids": ["t1", "t2"]})
        works = base.model_copy(update={"statement_id": "s5", "subject_id": "e7", "object_id": "e8",
                                        "predicate": "works_on", "valid_from": None, "valid_to": None})
        return graph_record("showcase", "A4", r.flags, r.documents, r.chunks, entities,
                            [*r.statements, turing, works]), entities

    def write_run(self, record, entities):
        write_graph_json(record, self.root / "graph.json")
        write_contract_files(self.root, entities=entities)

    def test_showcase_pass_and_fail_each_check(self):
        record, entities = self.golden()
        self.write_run(record, entities)
        result = eval_showcase(self.root, self.cfg)
        self.assertEqual(result, {"G1": "PASS", "G2": "PASS", "G3": "PASS",
                                  "G4": {"q1": "PASS", "q2": "PASS", "q3": "PASS", "q4": "PASS"},
                                  "G5": "PASS", "G6": "PASS", "gold_recall": 1.0})
        for check, change in [
            ("G1", lambda: self.write_run(record, [e.model_copy(update={"aliases": []}) for e in entities])),
            ("G2", lambda: self.write_run(record.model_copy(update={"statements": [
                s.model_copy(update={"support_count": 1, "candidate_ids": ["t1"]}) if s.statement_id == "s4" else s
                for s in record.statements]}), entities)),
            ("G3", lambda: self.write_run(record.model_copy(update={"statements": [
                s.model_copy(update={"valid_to": "2023"}) if s.statement_id == "s1" else s for s in record.statements]}), entities)),
            ("G5", lambda: self.write_run(record.model_copy(update={"documents": [
                d.model_copy(update={"text": "changed text"}) for d in record.documents]}), entities)),
        ]:
            change()
            self.assertEqual(eval_showcase(self.root, self.cfg)[check], "FAIL", check)
        self.write_run(record.model_copy(update={"statements": []}), entities)
        result = eval_showcase(self.root, self.cfg)
        self.assertEqual(set(result["G4"].values()), {"FAIL"})
        self.assertEqual(result["gold_recall"], 0.0)

    def test_showcase_all_entities_and_temporal_exclusivity(self):
        record, entities = self.golden()
        # IBM itself need not participate in an accepted edge for G1.
        self.write_run(record.model_copy(update={"statements": [s for s in record.statements if s.statement_id != "s3"],
                                                "entities": [e for e in record.entities if e.entity_id != "e4"]}), entities)
        self.assertEqual(eval_showcase(self.root, self.cfg)["G1"], "PASS")
        extra = record.statements[1].model_copy(update={"statement_id": "extra", "valid_from": None})
        self.write_run(record.model_copy(update={"statements": [*record.statements, extra]}), entities)
        self.assertEqual(eval_showcase(self.root, self.cfg)["G4"]["q2"], "FAIL")
        reverse = record.statements[3].model_copy(update={"statement_id": "reverse", "subject_id": "e6", "object_id": "e5"})
        self.write_run(record.model_copy(update={"statements": [*record.statements, reverse]}), entities)
        self.assertEqual(eval_showcase(self.root, self.cfg)["G2"], "FAIL")

    def test_g6_direction(self):
        record, entities = self.golden()
        division = Entity(entity_id="division", name="research division", aliases=[], kind="entity", mention_ids=[], resolver="identity")
        bad = record.statements[2].model_copy(update={"statement_id": "reversed", "predicate": "part_of", "object_id": "division"})
        self.write_run(record.model_copy(update={"entities": [*record.entities, division], "statements": [*record.statements, bad]}), [*entities, division])
        self.assertEqual(eval_showcase(self.root, self.cfg)["G6"], "FAIL")
        self.assertEqual(json.loads((self.root / "eval/showcase_checks.json").read_text())["details"]["G6"], {"reversed": ["reversed"], "flagged": []})
        flagged = bad.model_copy(update={"reasons": ["judge_no"]})
        self.write_run(record.model_copy(update={"entities": [*record.entities, division], "statements": [*record.statements, flagged]}), [*entities, division])
        self.assertEqual(eval_showcase(self.root, self.cfg)["G6"], "PASS")
        self.assertEqual(json.loads((self.root / "eval/showcase_checks.json").read_text())["details"]["G6"], {"reversed": [], "flagged": ["reversed"]})

    def test_webnlg_files_limits_and_counts(self):
        write_graph_json(self.record, self.root / "graph.json")
        ref = self.root / "reference.txt"
        ref.write_text("[]\n[]\n[]\n", encoding="utf-8")
        cfg = load_config(PROJECT_ROOT / "configs/experiments/webnlg10.yaml", mock=True)
        data = cfg.model_dump(mode="json")
        data["eval"]["webnlg_reference"] = str(ref)
        data["corpus"]["limit"] = 2
        cfg = from_resolved(data)
        scores = parse_eval_txt((self.recorded / "eval.txt").read_text(encoding="utf-8"))
        with patch("kgbuilder.evaluation.evaluate.run_webnlg_evaluator", return_value=scores):
            result = eval_webnlg(self.root, cfg)
        self.assertNotIn("per_doc", result)
        saved = json.loads((self.root / "eval/scores.json").read_text(encoding="utf-8"))
        self.assertEqual(len(saved["per_doc"]), 2)
        self.assertIn("evaluator_seconds", saved)
        self.assertEqual(len((self.root / "eval/pred.txt").read_text(encoding="utf-8").splitlines()), 2)
        self.assertEqual(len((self.root / "eval/ref.txt").read_text(encoding="utf-8").splitlines()), 2)
        write_graph_json(self.record.model_copy(update={"statements": self.record.statements[:1]}), self.root / "graph_strict.json")
        with patch("kgbuilder.evaluation.evaluate.run_webnlg_evaluator", return_value=scores) as evaluator:
            result = eval_webnlg(self.root, cfg)
        self.assertEqual(evaluator.call_count, 2)
        self.assertEqual(result["strict_level"]["strict"], scores["strict"])
        self.assertTrue((self.root / "eval/strict/scores.json").is_file())
        self.assertEqual((self.root / "eval/strict/ref.txt").read_bytes(), (self.root / "eval/ref.txt").read_bytes())
        data["corpus"]["limit"] = None
        with self.assertRaises(KgbError) as cm:
            eval_webnlg(self.root, from_resolved(data))
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
