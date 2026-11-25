"""The path from a person's answers to a runnable question file (graphrag/expert.py). No model call."""
import json
import tempfile
import unittest
from pathlib import Path

from graphrag import expert
from graphrag.coordinator import pooled
from graphrag.scoring import score_answer


class GoldValues(unittest.TestCase):
    def test_a_number_with_a_unit_is_a_number(self):
        self.assertEqual(expert.gold_value("1,955 ft"), 1955.0)
        self.assertEqual(expert.gold_value("8.5 in"), 8.5)
        self.assertEqual(expert.gold_value("24"), 24.0)

    def test_dates_and_words_stay_text(self):
        self.assertEqual(expert.gold_value("13 August 2016"), "2016-08-13")
        self.assertEqual(expert.gold_value("Monty Keown"), "Monty Keown")
        self.assertEqual(expert.gold_value("9 5/8 in casing"), "9 5/8 in casing")
        self.assertEqual(expert.gold_value("AK-3"), "AK-3")

    def test_alternatives_and_several_values(self):
        facts = expert.facts_of("p1", "Monty Keown | M. Keown; 1955 ft", "page 4")
        self.assertEqual([f["id"] for f in facts], ["p1.a1", "p1.a2"])
        self.assertEqual(facts[0]["alternatives"], ["M. Keown"])
        self.assertEqual(facts[1]["value"], 1955.0)
        self.assertEqual(facts[0]["source_note"], "page 4")


class PlainFields(unittest.TestCase):
    def test_an_answer_becomes_gold_the_scorer_accepts(self):
        data = expert.expand({"expected_lane": "end_of_well", "questions": [
            {"id": "p1", "question": "Total depth?", "answer": "1955 ft"}]})
        q, facts = data["questions"][0], {f["id"]: f for f in data["facts"]}
        self.assertNotIn("answer", q)
        self.assertTrue(score_answer(q, [facts[g] for g in q["gold"]], "answered", ["1,955"])["correct"])
        self.assertFalse(score_answer(q, [facts[g] for g in q["gold"]], "answered", ["1900"])["correct"])

    def test_not_stated_has_no_gold(self):
        data = expert.expand({"questions": [{"id": "p1", "question": "?", "answer": "Not stated",
                                             "expected_lane": "daily"}]})
        self.assertEqual((data["questions"][0]["gold"], data["facts"]), ([], []))

    def test_a_cause_question(self):
        data = expert.expand({"questions": [
            {"id": "c1", "question": "Why?", "answer": "a weather delay", "expected_lane": "reasoning",
             "key_words": "weather | rain", "problem_date": "13 August 2016"},
            {"id": "c2", "question": "Why did it wait?", "answer": "ask which", "expected_lane": "reasoning"},
            {"id": "c3", "question": "Why did X fail?", "answer": "not stated", "kind": "cause"}]})
        one, two, three = data["questions"]
        self.assertEqual(one["stated_causes"], [{"cause": "a weather delay", "terms": ["weather", "rain"], "chunks": []}])
        self.assertEqual((one["outcome"], one["gold_problem"]), ("answer", {"date": "2016-08-13"}))
        self.assertEqual((two["outcome"], two["stated_causes"]), ("ask_which", []))
        self.assertEqual(three["outcome"], "fallback")

    def test_a_question_with_gold_is_left_alone(self):
        q = {"id": "s01", "question": "?", "gold": ["y01"]}
        data = expert.expand({"questions": [q], "facts": [{"id": "y01", "value": 1}]})
        self.assertEqual(data["questions"], [q])


class Sheets(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())

    def test_a_collected_file_proposes_answers_marked_right(self):
        rows = expert.rows_of({"questions": [
            {"id": "a", "question": "Depth?", "system_answer": "1955 ft", "system_values": ["1955"],
             "feedback": [{"verdict": "wrong", "comment": "old"}, {"verdict": "right", "comment": "yes"}]},
            {"id": "b", "question": "Mud?", "system_answer": "9 ppg", "system_values": ["9"],
             "feedback": [{"verdict": "wrong", "comment": "it was 10.2"}]},
            {"id": "c", "question": "Rig?", "feedback": []}]})
        self.assertEqual([r["expected_answer"] for r in rows], ["1955", "", ""])
        self.assertEqual(rows[1]["comment"], "it was 10.2")
        self.assertEqual(rows[0]["mark"], "right")

    def test_round_trip_through_a_sheet(self):
        sheet = self.folder / "pilot.csv"
        expert.write_sheet([dict(row, id=f"p{n}") for n, row in enumerate(expert.EXAMPLES)], sheet)
        data, left_out = expert.build(expert.read_sheet(sheet), "pilot_v1", "A. Expert", True, "2026-12-01")
        self.assertEqual((len(data["questions"]), left_out), (5, []))
        self.assertTrue(data["status"].startswith("EXPERT"))
        self.assertEqual(expert.problems(data), [])
        path = self.folder / "pilot_v1.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        questions, gold = pooled([str(path)])
        self.assertEqual([q["expected"] for q in questions], ["end_of_well", "end_of_well", "events", "daily", "reasoning"])
        self.assertEqual(gold["pilot_v1:p0.a1"]["value"], 1955.0)
        self.assertEqual(questions[0]["gold"], ["pilot_v1:p0.a1"])

    def test_excel_semicolons_examples_and_empty_rows(self):
        sheet = self.folder / "s.csv"
        sheet.write_text("﻿id;question;expected_answer;lane\nexample-1;Skip me?;1;daily\n"
                         ";Depth of AK-3?;1955;End of well\nq9;No answer yet?;;daily\n", encoding="utf-8")
        data, left_out = expert.build(expert.read_sheet(sheet), "t_v1", "Tri", False, "2026-12-01")
        self.assertEqual([q["id"] for q in data["questions"]], ["q02"])
        self.assertEqual(data["questions"][0]["expected_lane"], "end_of_well")
        self.assertEqual(left_out, ["q9"])
        self.assertIn("not reviewed by a drilling expert", data["status"])

    def test_a_sheet_without_the_columns_is_refused(self):
        sheet = self.folder / "bad.csv"
        sheet.write_text("a,b\n1,2\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            expert.read_sheet(sheet)


class Checks(unittest.TestCase):
    def test_problems_are_named(self):
        found = expert.problems({"questions": [
            {"id": "a", "question": "?", "gold": ["missing"], "expected_lane": "daily"},
            {"id": "a", "question": "", "gold": []},
            {"id": "c", "question": "Why?", "answer": "bad cement", "expected_lane": "reasoning"}]})
        text = "\n".join(found)
        for part in ("'missing' is not in facts", "used twice", "no question text", "no expected lane", "no key words"):
            self.assertIn(part, text)

    def test_the_frozen_sets_still_load(self):
        for path in sorted((expert.GOLD).glob("ak3_reasoning_probe_v*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(expert.expand(data)["questions"], data["questions"])


if __name__ == "__main__":
    unittest.main()
