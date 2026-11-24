"""Defects found by the code review of 25 November 2026 (Track B log B-F68 to B-F70), each pinned by a test.
No model, store or corpus needed."""
import unittest

from graphrag import reasoning
from graphrag.citations import resolve
from graphrag.data import Chunk
from graphrag.events import Event, plan_value
from graphrag.retrieval import BM25, question_dates
from graphrag.scoring import score_answer
from graphrag.validate import written_in

EVENTS = [Event("2016-08-20", "17:00", "18:00", 1.0, 176, "STUCK", "", ["c"], "KICK"),
          Event("2016-08-21", "0:00", "0:00", 24.0, 176, "KICK", "", ["d"], "KICK"),
          Event("2016-08-25", "0:00", "6:00", 6.0, 400, "WOW", "", ["e"], "WAIT")]
NPT = {"operation": "total_hours", "well": "AK-3", "code": "", "non_productive": True, "npt_code": "",
       "date_from": "", "date_to": "", "group_by": "", "depth_ft": 0, "min_hours_per_day": 0}


class PlanTests(unittest.TestCase):
    def total(self, **changes):
        return plan_value({**NPT, **changes}, EVENTS)[0]

    def test_a_date_range_selects_its_days(self):
        self.assertEqual(self.total(date_from="2016-08-20", date_to="2016-08-21"), ["25"])

    def test_a_date_written_in_words_means_the_same_days_not_the_whole_well(self):
        self.assertEqual(self.total(date_from="20 August 2016", date_to="21 August 2016"), ["25"])

    def test_a_date_code_cannot_read_gives_no_result(self):
        self.assertEqual(self.total(date_from="late August"), [])
        self.assertEqual(self.total(date_from="2016-08"), [])

    def test_a_reversed_range_a_negative_number_or_an_unknown_operation_gives_no_result(self):
        self.assertEqual(self.total(date_from="2016-08-25", date_to="2016-08-20"), [])
        self.assertEqual(self.total(min_hours_per_day=-5), [])
        self.assertEqual(plan_value({**NPT, "operation": "delete_everything"}, EVENTS)[0], [])
        self.assertEqual(plan_value({}, EVENTS)[0], [])


class ScoringTests(unittest.TestCase):
    def test_with_no_gold_only_saying_nothing_is_stated_is_right(self):
        for status, right in (("not_stated", True), ("not_found_in_graph", True), ("invalid", False),
                              ("withheld", False), ("ask_which", False), ("answered", False)):
            self.assertEqual(score_answer({}, [], status, [])["correct"], right, status)

    def test_an_answer_to_a_question_with_no_gold_is_wrong(self):
        self.assertFalse(score_answer({}, [], "answered", ["1955"])["correct"])


class FactCheckTests(unittest.TestCase):
    def test_a_number_is_not_written_where_only_its_digits_are(self):
        for value, text in ((8, "drilled to 833' in 2010"), ("150", "at approximately 1500' elevation"),
                            ("180", "x-126726.1, y-78180.6"), ("19", "a depth of 1,955 ft"), ("41", "41.5 ft")):
            self.assertFalse(written_in(value, text), (value, text))

    def test_the_same_number_written_another_way_is_found(self):
        for value, text in ((1955, "a depth of 1,955 ft"), ("5.5", "5.500 at 1000"), ("12", "| 12.00 |"),
                            ("0.7", "| 0.70 |"), ("3", "Casing 13-3/8 set"), ("2016-08-18", "spud on 18 August 2016")):
            self.assertTrue(written_in(value, text), (value, text))


class CitationTests(unittest.TestCase):
    def test_a_reply_with_a_number_where_text_is_asked_does_not_crash(self):
        found = resolve({"chunk": "c0001", "quote": None, "value": 1955}, ["d#c0001"], {"d#c0001": "depth 1,955 ft"}, "d")
        self.assertEqual(found, ("d#c0001", "by_value"))
        self.assertEqual(resolve({}, ["d#c0001"], {"d#c0001": "depth"}, "d"), (None, "unsupported"))

    def test_a_cause_needs_a_word_of_the_report_behind_it(self):
        items = [{"id": "E1", "chunk": "c", "text": "Work to free stuck pipe, due to a plugged inner barrel"}]
        listed = [{"cause": "offset well pressure", "citations": [{"id": "E1", "quote": "a"}]},
                  {"cause": "plugged inner barrel", "citations": [{"id": "E1", "quote": "plugged inner barrel"}]}]
        kept, dropped, _ = reasoning.check(listed, items)
        self.assertEqual(([k["cause"] for k in kept], dropped), (["plugged inner barrel"], 1))


class ProblemCodeTests(unittest.TestCase):
    def test_an_activity_code_given_as_the_non_productive_code_still_finds_the_problem(self):
        frame = {"plan": {"well": "AK-3"},
                 "problem": {"date": "2016-08-20", "depth_ft": 0, "npt_code": "STUCK", "keywords": ["stuck", "pipe"]}}
        found = reasoning.find_problems(frame, EVENTS)
        self.assertEqual([(p.events[0].date, p.events[0].npt_code) for p in found], [("2016-08-20", "KICK")])

    def test_the_day_asked_about_outranks_a_code_the_model_chose(self):
        frame = {"plan": {"well": "AK-3"},
                 "problem": {"date": "2016-08-25", "depth_ft": 0, "npt_code": "KICK", "keywords": []}}
        self.assertEqual([p.events[0].npt_code for p in reasoning.find_problems(frame, EVENTS)], ["WAIT"])

    def test_on_a_day_asked_about_one_keyword_names_an_activity_that_is_not_non_productive(self):
        events = [*EVENTS, Event("2016-08-19", "9:30", "21:30", 12.0, 49, "WOC", "Lay plywood on site for walk way due to muddy site", ["p"])]
        dated = {"plan": {"well": "AK-3"}, "problem": {"date": "2016-08-19", "depth_ft": 0, "npt_code": "", "keywords": ["plywood", "walkway"]}}
        self.assertEqual([p.events[0].date for p in reasoning.find_problems(dated, events)], ["2016-08-19"])
        undated = {"plan": {"well": "AK-3"}, "problem": {"date": "", "depth_ft": 0, "npt_code": "", "keywords": ["plywood", "walkway"]}}
        self.assertEqual(reasoning.find_problems(undated, events), [])

    def test_a_real_non_productive_code_still_selects_by_code(self):
        frame = {"plan": {"well": "AK-3"}, "problem": {"date": "", "depth_ft": 0, "npt_code": "wait", "keywords": []}}
        self.assertEqual([p.events[0].npt_code for p in reasoning.find_problems(frame, EVENTS)], ["WAIT"])


class StatedCauseTests(unittest.TestCase):
    TEXT = ("Core ahead to 176 ft, high torque, stuck pipe, taking steam kick. Work to free stuck pipe, free hot water "
            "flowing from annulus, due to plugged inner barrel. Crews at lodge for night | Waiting on weather to fly rods")

    def item(self, quote):
        return {"cause": "x", "citations": [{"evidence": "E1", "quote": quote}]}

    def test_a_quote_in_a_clause_that_gives_a_reason_is_a_stated_cause(self):
        for quote in ("plugged inner barrel", "due to plugged inner barrel", "Waiting on weather"):
            self.assertTrue(reasoning.stated_as_a_cause(self.item(quote), {"E1": self.TEXT}), quote)

    def test_a_quote_of_something_that_only_happened_is_not(self):
        for quote in ("taking steam kick", "high torque, stuck pipe", "Crews at lodge for night"):
            self.assertFalse(reasoning.stated_as_a_cause(self.item(quote), {"E1": self.TEXT}), quote)


class DateTests(unittest.TestCase):
    def test_dates_are_read_in_the_ways_people_write_them(self):
        for text in ("on 20 August 2016", "on August 20, 2016", "on 2016-08-20", "on 20th Aug 2016", "on 20 Aug. 2016"):
            self.assertEqual(question_dates(text), {"2016-08-20"}, text)

    def test_a_range_gives_every_day_in_it(self):
        days = {"2016-08-20", "2016-08-21", "2016-08-22"}
        self.assertEqual(question_dates("from 20-22 August 2016"), days)
        self.assertEqual(question_dates("from 20 to 22 August 2016"), days)

    def test_numbers_that_are_not_dates_are_left_alone(self):
        self.assertEqual(question_dates("the 12-25 section in May 2016 at 1,725 ft"), set())


class SearchTests(unittest.TestCase):
    def test_a_search_over_no_passages_returns_nothing(self):
        index = BM25([Chunk("a", "d", 1, "text", None, "stuck pipe at 176 ft")])
        self.assertEqual(index.search("stuck pipe", 5, allowed=set()), [])
        self.assertEqual(len(index.search("stuck pipe", 5)), 1)


class ProbeScoreTests(unittest.TestCase):
    ROW = {"status": "answered", "lanes": ["passages"], "reasoning": None}

    def test_a_question_about_a_problem_that_never_happened_is_right_only_when_nothing_is_stated(self):
        q = {"outcome": "fallback", "stated_causes": []}
        self.assertFalse(reasoning.score(self.ROW, q)["correct"])
        self.assertTrue(reasoning.score({**self.ROW, "status": "not_stated"}, q)["correct"])
        self.assertFalse(reasoning.score({**self.ROW, "status": "not_stated", "lanes": ["reasoning"]}, q)["correct"])

    def test_a_broken_reply_is_not_a_correct_empty_answer(self):
        q = {"outcome": "ask_which", "stated_causes": []}
        row = {"status": "ask_which", "lanes": ["reasoning"], "reasoning": {"stated": [], "valid": False}}
        self.assertFalse(reasoning.score(row, q)["correct"])
        row["reasoning"]["valid"] = True
        self.assertTrue(reasoning.score(row, q)["correct"])


if __name__ == "__main__":
    unittest.main()
