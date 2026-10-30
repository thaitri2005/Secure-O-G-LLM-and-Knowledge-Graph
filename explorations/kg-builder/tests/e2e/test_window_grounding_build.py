"""Replay WINDOW_GROUNDING build mechanisms and preserve byte-identical legacy graphs."""
from __future__ import annotations

import json
import unittest

from helpers import PROJECT_ROOT, SENTENCE_GROUNDING, WINDOW_GROUNDING, clean_dir, run_kgb, sets
from kgbuilder.core.text import number_tokens, read_jsonl, sha256_file, surface_key


class WindowGroundingBuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = clean_dir(PROJECT_ROOT / "runs/_test/window_grounding_build")
        cls.outputs = {}
        for name in ("webnlg10", "2wiki10", "showcase"):
            for label, pins in (("window", WINDOW_GROUNDING), ("legacy", SENTENCE_GROUNDING)):
                if label == "legacy" and not (PROJECT_ROOT / "runs/reference/ablation_sentence_grounding" / name / "A4/graph.json").is_file():
                    raise AssertionError("Required legacy reference graph is missing: " + name)
                out = cls.root / label / name / "A4"
                config = "twowiki10" if name == "2wiki10" else name
                result = run_kgb(["build", "--config", f"configs/experiments/{config}.yaml", "--ablation", "A4", "--mock",
                                  *sets(pins), "--out", str(out), "--overwrite"], test_id=f"window_grounding_build_{label}_{name}", timeout=1800)
                if result.returncode:
                    raise AssertionError(result.stdout + result.stderr)
                cls.outputs[label, name] = out
        for name, mode in (("webnlg10", "webnlg"), ("showcase", "showcase")):
            result = run_kgb(["eval", mode, "--run", str(cls.outputs["window", name])], timeout=1800)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)

    def metrics(self, name):
        return json.loads((self.outputs["window", name] / "metrics.json").read_text(encoding="utf-8"))

    def test_replay_and_legacy(self):
        for (label, name), out in self.outputs.items():
            metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["llm"]["cache_misses"], 0)
            self.assertFalse(any(r.get("miss") for r in read_jsonl(out / "llm_calls.jsonl")))
            if label == "legacy":
                self.assertEqual(sha256_file(out / "graph.json"), sha256_file(PROJECT_ROOT / "runs/reference/ablation_sentence_grounding" / name / "A4/graph.json"))

    def test_webnlg_date(self):
        out = self.outputs["window", "webnlg10"]
        candidate = next(r for r in read_jsonl(out / "candidates.jsonl")
                         if (r["subject"], r["predicate"], r["object"]) == ("Alan_B._Miller_Hall", "completionDate", '"1 June 2009"'))
        self.assertEqual(candidate["evidence"]["grounding"], "exact")
        stmt = next(r for r in read_jsonl(out / "statements.jsonl") if candidate["candidate_id"] in r["candidate_ids"])
        self.assertTrue(any(e["grounding"] == "exact" for e in stmt["evidence"]))
        scores = json.loads((out / "eval/scores.json").read_text(encoding="utf-8"))
        print("WINDOW_GROUNDING webnlg10 A4 F1", scores["strict"]["F1"], "weak", self.metrics("webnlg10")["rejected_by_reason"].get("weak_evidence", 0),
              "ground_rules", self.metrics("webnlg10")["ground_rules"])

    def test_number_guard(self):
        entities = read_jsonl(self.outputs["window", "2wiki10"] / "entities.jsonl")
        by_name = {name: e["entity_id"] for e in entities for name in [e["name"], *e["aliases"]]}
        earls = [f"{n} Earl of Strathmore and Kinghorne" for n in ("3rd", "4th", "6th", "8th")]
        self.assertEqual(len({by_name[name] for name in earls}), 4)
        self.assertEqual(by_name["Cnut"], by_name["Cnut the Great"])
        for entity in entities:
            names = [entity["name"], *entity["aliases"]]
            for a in names:
                for b in names:
                    if surface_key(a) != surface_key(b):
                        self.assertEqual(number_tokens(a), number_tokens(b), (a, b))
        print("WINDOW_GROUNDING Earl ids", {n: by_name[n] for n in earls})
        print("WINDOW_GROUNDING 2wiki10 A4 weak", self.metrics("2wiki10")["rejected_by_reason"].get("weak_evidence", 0),
              "ground_rules", self.metrics("2wiki10")["ground_rules"])

    def test_showcase(self):
        checks = json.loads((self.outputs["window", "showcase"] / "eval/showcase_checks.json").read_text(encoding="utf-8"))["status"]
        for key in ("G1", "G2", "G3", "G5"):
            self.assertEqual(checks[key], "PASS")
        self.assertEqual(checks["G4"], dict.fromkeys(("q1", "q2", "q3", "q4"), "PASS"))
        print("WINDOW_GROUNDING showcase A4 G6", checks["G6"], "ground_rules", self.metrics("showcase")["ground_rules"])

    def test_soft_validation_levels(self):
        out = self.outputs["window", "2wiki10"]
        statements = read_jsonl(out / "statements.jsonl")
        rejected = read_jsonl(out / "rejected.jsonl")
        flags = {s["statement_id"] for s in statements if set(s["reasons"]) & {"weak_evidence", "judge_no"}}
        self.assertTrue(all(s["status"] == "accepted" for s in statements if "weak_evidence" in s["reasons"]))
        self.assertFalse(any("weak_evidence" in r["reasons"] for r in rejected))
        self.assertEqual(self.metrics("2wiki10")["statements_rejected"], sum(r["kind"] == "statement" for r in rejected))
        strict = json.loads((out / "graph_strict.json").read_text(encoding="utf-8"))
        full = json.loads((out / "graph.json").read_text(encoding="utf-8"))
        self.assertEqual({s["statement_id"] for s in strict["statements"]}, {s["statement_id"] for s in full["statements"]} - flags)
        self.assertEqual(self.metrics("2wiki10")["statements_flagged"], len(flags))
        print("WINDOW_GROUNDING 2wiki10 A4 flagged weak_evidence", self.metrics("2wiki10")["flagged_by_reason"].get("weak_evidence", 0))


if __name__ == "__main__":
    unittest.main()
