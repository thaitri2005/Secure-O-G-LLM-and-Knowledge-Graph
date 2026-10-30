"""Artifact-only CLI reproduces the pinned ablation audit without mutating inputs."""
from __future__ import annotations

import json
import unittest

from helpers import PROJECT_ROOT, run_kgb


class AnalyzeCliTest(unittest.TestCase):
    def test_recorded_analysis(self):
        if not (PROJECT_ROOT / "runs/reference/ablation_sentence_grounding/ablation.json").is_file():
            self.fail("Required published test input is missing")
        outputs = ["runs/_test/window_analysis", "runs/_test/window_analysis_2"]
        for out in outputs:
            proc = run_kgb(["analyze", "--run", "runs/reference/ablation_sentence_grounding", "--out", out, "--overwrite"])
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertFalse(list((PROJECT_ROOT / out).rglob("llm_calls.jsonl")))
        self.assertEqual((PROJECT_ROOT / outputs[0] / "analysis.json").read_bytes(), (PROJECT_ROOT / outputs[1] / "analysis.json").read_bytes())
        report = json.loads((PROJECT_ROOT / outputs[0] / "analysis.json").read_text(encoding="utf-8"))
        web = report["webnlg"]["webnlg10"]
        transitions = {(r["from"], r["to"]): r for r in web["transitions"]}
        lost = transitions["A2", "A4"]["lost"]
        self.assertEqual(lost, [{"doc": 8, "triple": ["Alan_B._Miller_Hall", "completionDate", '"1_June_2009"'],
                                 "cause": "weak_evidence", "gold_correct": True}])
        self.assertEqual(transitions["A2", "A4"]["gained"], [])
        lost = transitions["A4", "A5"]["lost"]
        self.assertEqual(len(lost), 2)
        self.assertEqual({r["triple"][1] for r in lost}, {"location", "elevationAboveTheSeaLevel"})
        self.assertTrue(all(r["doc"] == 1 and r["cause"] == "judge_no" and r["gold_correct"] for r in lost))
        self.assertEqual((web["residual"]["A2"]["extra"], web["residual"]["A2"]["missing"]), (12, 14))
        weak = report["rejected"]["2wiki10/A4"]["weak"]
        self.assertEqual((weak["n"], weak["object_in_chunk"], weak["unlocated"]), (31, 31, 0))
        self.assertEqual(weak["distance"], {"0": 6, "1": 16, "2": 9})
        for name, recorded, reparsed, finish in [("showcase", (3, 0, 4), (5, 2, 0), 5),
                                                ("webnlg10", (7, 2, 21), (23, 5, 2), 17),
                                                ("2wiki10", (100, 24, 91), (177, 30, 8), 155)]:
            judge = report["judge"][name + "/A5"]
            for key, expected in [("recorded", recorded), ("reparsed", reparsed)]:
                self.assertEqual(tuple(judge[key][k] for k in ("yes", "no", "unparsed")), expected)
                self.assertEqual(judge[key]["errors"], 0)
            self.assertEqual(judge["finish_length"], finish)
        for kind, n in [("recorded", 2), ("reparsed", 5)]:
            self.assertEqual(report["judge"]["webnlg10/A5"]["no_vs_gold"][kind], {"n_no": n, "gold_correct": n, "precision": 0.})
        self.assertEqual(report["judge"]["showcase/A5"]["no_vs_gold"]["reparsed"], {"n_no": 2, "gold_correct": 2, "precision": 0.})
        pairs = {(r["row"], r["vs"]): r for r in report["qa"]["pairs"]}
        for row, vs, expected in [("graph@A4", "graph@A0", (0, 2, 8, .5)), ("graph@A5", "graph@A4", (0, 1, 9, 1.))]:
            self.assertEqual(tuple(pairs[row, vs][k] for k in ("wins", "losses", "ties", "sign_p")), expected)
        aliases = report["alias"]["2wiki10/A4"]
        self.assertEqual((aliases["groups"], aliases["number_conflicts"]), (3, 1))
        self.assertEqual([r["name"] for r in aliases["items"] if r["conflict"]], ["4th Earl of Strathmore and Kinghorne"])

    def test_paths(self):
        if not (PROJECT_ROOT / "runs/reference/ablation_sentence_grounding/ablation.json").is_file():
            self.fail("Required published test input is missing")
        for source, out in [("runs/reference/ablation_sentence_grounding", "runs/reference/ablation_sentence_grounding/x"), ("tests/fixtures", "runs/_test/analysis_bad"),
                            ("runs/reference/ablation_sentence_grounding", "runs"), ("runs/_test/missing_analysis_input", "runs/_test/analysis_bad"),
                            ("runs/reference/ablation_sentence_grounding", "runs/reference"), ("runs/reference/ablation_sentence_grounding", "runs/reference/ablation_sentence_grounding")]:
            proc = run_kgb(["analyze", "--run", source, "--out", out, "--overwrite"])
            self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
