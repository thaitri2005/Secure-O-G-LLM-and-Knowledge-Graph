"""Synthetic tests of artifact analysis, matching and paired statistics."""
from __future__ import annotations

import unittest

from helpers import PROJECT_ROOT, clean_dir
from kgbuilder.core import text
from kgbuilder.core.config import ConfigError
from kgbuilder.evaluation import analysis


class AnalysisTest(unittest.TestCase):
    def setUp(self):
        self.root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/analysis")

    def test_statistics(self):
        for wins, losses, expected in [(0, 2, .5), (0, 1, 1), (1, 9, .0215), (0, 0, 1)]:
            self.assertEqual(analysis.sign_test(wins, losses), expected)
        self.assertEqual(analysis.paired_bootstrap([0.] * 10), {"n": 10, "mean": 0., "lo": 0., "hi": 0.})
        self.assertEqual(analysis.paired_bootstrap([1, -1, .3]), analysis.paired_bootstrap([1, -1, .3]))
        self.assertEqual(analysis.paired_bootstrap([]), {"n": 0, "mean": None, "lo": None, "hi": None})

    def test_token_cost(self):
        rows = [{"stage": "qa.text", "cache_hit": False, "content": "ok", "seconds": sec,
                 "usage": {"prompt_tokens": pt, "completion_tokens": 10},
                 "messages": [{"role": "user", "content": "x" * (4 * pt)}]}
                for pt, sec in [(100, 3.), (200, 5.)]]
        self.assertEqual(analysis.fit_token_cost(rows), {"a": .02, "b": .1, "chars_per_token": 4., "n_rows": 2})
        with self.assertRaisesRegex(ConfigError, "no reference reader rows"):
            analysis.fit_token_cost(rows[:1])
        reference = self.root / "reference"
        text.write_jsonl(reference / "llm_calls.jsonl", [*rows, {**rows[0], "stage": "judge", "usage": {"prompt_tokens": 100, "completion_tokens": 6}}])
        planned = [{"key": key, "planned": True, "stage": "judge", "asked_max_tokens": 32,
                    "messages": [{"role": "user", "content": "x" * 400}]} for key in ("a", "b", "a")]
        root = self.root / "plan"
        text.write_jsonl(root / "llm_calls.jsonl", planned)
        classifier = lambda r: "qa" if r["stage"].startswith("qa.") else r["stage"]
        report = analysis.plan_cost(root, classifier, [reference])
        self.assertEqual(report["kinds"]["judge"], {"new_calls": 2, "mean_prompt_tokens_est": 100.,
                                                  "minutes_low": round(2 * (.02 * 100 + .1 * 6) / 60, 1),
                                                  "minutes_high": round(2 * (.02 * 100 + .1 * 32) / 60, 1)})
        text.write_jsonl(root / "llm_calls.jsonl", [{**r, "stage": "concept"} for r in planned])
        report = analysis.plan_cost(root, classifier, [reference])
        self.assertEqual(report["kinds"]["concept"]["minutes_low"], round(2 * (2 + .1 * (26 / 3)) / 60, 1))

    def test_classes(self):
        cases = [(("X", "completionDate", '"1_June_2009"'), ("X", "completionDate", "2009-06-01"), "literal"),
                 (("X", "height", "610_(metres)"), ("X", "height", "610.0"), "literal"),
                 (("Su\u00e1rez\u2013Barajas", "in", "X"), ("Suarez-Barajas", "in", "X"), "surface"),
                 (("X", "in", "Y"), ("Y", "in", "X"), "direction"),
                 (("X", "in", "Y"), ("X", "at", "Y"), "predicate"),
                 (("Israel", "ethnicGroup", "Arabs"), ("Israel", "ethnicGroup", "Arab_citizens_of_Israel"), "partial_entity"),
                 (("X", "in", "Y"), ("Z", "at", "W"), "other")]
        for a, b, expected in cases:
            self.assertEqual(analysis.classify(a, b), expected)

    def test_webnlg_and_weak_distance(self):
        entities = [{"entity_id": "s", "name": "Alice", "aliases": []}, {"entity_id": "o", "name": "Paris", "aliases": []}]
        value = "Alice travelled. She lives in Paris."
        stmt = {"statement_id": "s1", "subject_id": "s", "predicate": "lives_in", "object_id": "o",
                "source_doc_id": "d", "reasons": ["weak_evidence"], "evidence_span": {"chunk_id": "c", "doc_id": "d"}}
        for level, pred in [("A2", [["Alice", "lives_in", "Paris"]]), ("A4", [])]:
            path = self.root / level
            text.write_json(path / "metrics.json", {})
            text.write_json(path / "graph.json", {"documents": [{"doc_id": "d"}]})
            text.write_jsonl(path / "entities.jsonl", entities)
            text.write_jsonl(path / "documents.jsonl", [{"doc_id": "d", "text": value}])
            text.write_jsonl(path / "chunks.jsonl", [{"chunk_id": "c", "text": value, "char_start": 0}])
            text.write_jsonl(path / "rejected.jsonl", [{"kind": "statement", "record": stmt}] if level == "A4" else [])
            (path / "eval").mkdir()
            (path / "eval/pred.txt").write_text(repr(pred) + "\n", encoding="utf-8")
            (path / "eval/ref.txt").write_text(repr([["Alice", "lives_in", "Paris"]]) + "\n", encoding="utf-8")
        report = analysis.webnlg_report(self.root)
        self.assertEqual(report["transitions"][0]["lost"][0]["cause"], "weak_evidence")
        self.assertTrue(report["transitions"][0]["lost"][0]["gold_correct"])
        self.assertEqual(analysis.rejected_report(self.root / "A4")["weak"]["distance"], {"1": 1})

    def test_aliases(self):
        text.write_jsonl(self.root / "entities.jsonl", [{"entity_id": "e", "name": "4th Earl", "aliases": ["8th Earl"]}])
        report = analysis.alias_report(self.root)
        self.assertEqual((report["groups"], report["number_conflicts"]), (1, 1))

    def test_qa_pairs_and_ids(self):
        for label, values in [("A0", [1., 1., 0.]), ("A4", [0., 0., 0.])]:
            text.write_jsonl(self.root / label / "answers.jsonl", [
                {"qid": str(i), "row": "graph@" + label, "f1": f1, "facts": [label], "retrieved": [label], "seeds": [label]}
                for i, f1 in enumerate(values)])
        dirs = [self.root / "A0", self.root / "A4"]
        report = analysis.qa_report(dirs)
        self.assertEqual(report["pairs"][0]["sign_p"], .5)
        self.assertEqual(report["pairs"][0]["losses"], 2)
        self.assertEqual(len(report["diffs"]), 2)
        self.assertEqual(analysis.qa_report([*dirs, dirs[0]])["duplicate_rows"], ["graph@A0"])
        text.write_jsonl(self.root / "bad/answers.jsonl", [{"qid": "different", "row": "text"}])
        with self.assertRaisesRegex(ConfigError, "QA question ids differ"):
            analysis.qa_report([*dirs, self.root / "bad"])


if __name__ == "__main__":
    unittest.main()
