"""The Track B UI (graphrag/ui.py): replay of recorded runs, lane choice, and live answers with a stand-in model."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from graphrag import ui


class FakeClient:
    """Answers every question with the total depth, quoting the passage that states it."""

    def __init__(self, *args, **kwargs):
        pass

    def chat(self, messages, schema=None, max_tokens=None):
        parsed = {"evidence": "The report states the depth.", "status": "answered",
                  "answers": [{"value": "1,955", "unit": "ft", "chunk": "c0002", "quote": "1,955 feet"}]}
        return SimpleNamespace(parsed=parsed, content=json.dumps(parsed), prompt_tokens=100, completion_tokens=20,
                               seconds=0.1, cached=False)


class UiTests(unittest.TestCase):
    def test_runs_list_recorded_answer_runs_with_their_method(self):
        runs = {r["name"]: r for r in ui.list_runs()}
        self.assertEqual(runs["E28_heldout_graph"]["method"], "Event graph")
        self.assertEqual(runs["E27_design_prototype"]["method"], "Per-well fact graph")

    def test_replaying_an_event_graph_answer_shows_the_events_it_was_computed_from(self):
        row = ui.run_view("E28_heldout_graph")["rows"][0]
        self.assertIn("TRPI", row["question"])
        self.assertEqual(row["values"], ["13"])
        self.assertEqual(len(row["events"]), 8)
        self.assertEqual(sum(e["hours"] for e in row["events"]), 13)

    def test_replaying_an_end_of_well_answer_shows_the_cited_passage(self):
        row = ui.run_view("E27_design_prototype")["rows"][0]
        self.assertIn("1,955", row["citations"][0]["text"])

    def test_run_names_outside_the_results_folder_are_refused(self):
        for name in ("../CLAUDE", "E28_heldout_graph/../x", "nope"):
            with self.assertRaises(FileNotFoundError):
                ui.run_view(name)

    def test_lane_is_chosen_from_the_question(self):
        self.assertEqual(ui.choose_lane("How many non-productive hours were logged?", "auto"), "daily")
        self.assertEqual(ui.choose_lane("What was the mud weight on 18 August 2016?", "auto"), "daily")
        self.assertEqual(ui.choose_lane("What casing was set in well 56-32?", "auto"), "eowr")
        self.assertEqual(ui.choose_lane("anything", "eowr"), "eowr")

    def test_live_answer_without_a_model_server_says_so(self):
        with patch.object(ui, "endpoint_status", return_value={"up": False, "detail": "nothing answers"}):
            self.assertIn("No model to answer with", ui.ask("What total depth did AK-3 reach?")["error"])

    def test_live_end_of_well_answer_is_cited_and_checked(self):
        with patch.object(ui, "endpoint_status", return_value={"up": True, "detail": "test"}), \
                patch("graphrag.client.ModelClient", FakeClient):
            out = ui.ask("What total depth did well AK-3 reach?", lane="eowr")
        self.assertEqual(out["lane"], "eowr")
        self.assertEqual(out["values"], ["1955"])
        # The stand-in cites c0002 whether or not it was retrieved; code keeps the citation only if the quote is in a
        # retrieved passage, else reattaches it by quote or value, so the passage shown always holds the answer.
        citation = out["citations"][0]
        self.assertTrue(citation["id"].startswith("gdr882_ak3_eowr#"))
        self.assertIn("1955", citation["text"].replace(",", ""))
        self.assertIn(citation["how"], ("model", "by_quote", "by_value"))


if __name__ == "__main__":
    unittest.main()
