"""Track B's lanes and coordinator (specification §8.1), with stand-in models: no server is needed."""
import hashlib
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from graphrag import baseline, client, events
from graphrag.events import Event

GOLDEN = Path(__file__).parent / "fixtures/graphrag_answer_requests.json"
DEPTH_ANSWER = {"evidence": "The report states the depth.", "status": "answered",
                "answers": [{"value": "1,955", "unit": "ft", "chunk": "c0002", "quote": "1,955 feet"}]}
NOT_STATED = {"evidence": "", "status": "not_stated", "answers": []}


class RecordingClient:
    """Returns one fixed answer and keeps every request it was sent."""

    def __init__(self, answer=DEPTH_ANSWER):
        self.answer, self.calls = answer, []

    def chat(self, messages, schema=None, max_tokens=None):
        self.calls.append({"messages": messages, "schema": schema, "max_tokens": max_tokens})
        return SimpleNamespace(parsed=self.answer, content=json.dumps(self.answer), prompt_tokens=100,
                               completion_tokens=20, seconds=0.1, cached=False)


def recorded_requests() -> dict:
    """The requests two baseline runs send: the prototype questions, and the probe with multi-well routing."""
    chunks = baseline.pool("three")
    retriever = baseline.build("wells:bm25", chunks)
    retrieve = lambda q: ([c for c, _ in retriever.search(q, 5)], "")
    out = {}
    for name, kwargs in (("prototype", {"questions": "prototype"}),
                         ("probe_multi_well", {"questions": "probe", "multi_well_format": "evidence_first"})):
        recording = RecordingClient()
        baseline.answer_questions(retrieve, chunks, recording, **kwargs)
        # A hash of each whole request keeps the fixture small; any changed character changes it.
        out[name] = [hashlib.sha256(json.dumps([c["messages"], c["schema"], c["max_tokens"]], sort_keys=True)
                                    .encode("utf-8")).hexdigest() for c in recording.calls]
    return out


def plan(operation, **fields):
    """A complete query plan: every PLAN_SCHEMA field, empty unless given."""
    empty = {"well": "AK-3", "code": "", "non_productive": False, "npt_code": "", "date_from": "", "date_to": "",
             "group_by": "", "min_hours_per_day": 0, "depth_ft": 0}
    return {"operation": operation, **empty, **fields}


def sample_events():
    return [Event("2016-08-20", "0:00", "9:30", 9.5, 100, "DRIL", "drilling ahead", ["a"]),
            Event("2016-08-20", "9:30", "10:00", 0.5, 100, "SURV", "", ["b"]),
            Event("2016-08-20", "17:00", "18:00", 1.0, 176, "STUCK", "", ["c"], "KICK"),
            Event("2016-08-21", "0:00", "0:00", 24.0, 176, "KICK", "", ["d"], "KICK"),
            Event("2016-08-22", "0:00", "6:00", 6.0, 300, "DRIL", "", ["e", "a"])]


class RoleTests(unittest.TestCase):
    def test_roles_file_names_the_four_roles_on_known_endpoints(self):
        roles = client.load_roles()
        self.assertEqual(set(roles), {"frame", "answer", "extract", "embed"})
        self.assertEqual(roles["answer"], {"endpoint": "local-llama", "model": "qwen3-8b"})
        self.assertTrue(all(r["endpoint"] in client.load_endpoints() for r in roles.values()))

    def test_client_for_a_role_uses_its_endpoint_and_model(self):
        made = client.client_for("embed", cache_dir=None)
        self.assertEqual((made.endpoint.name, made.model), ("local-embed", "qwen3-embedding-0.6b"))

    def test_unknown_role_is_refused(self):
        with self.assertRaises(KeyError):
            client.client_for("summarize")


class PlanValueTests(unittest.TestCase):
    def setUp(self):
        self.events = sample_events()

    def test_total_hours_gives_one_number_in_hours(self):
        values, unit, text, rows = events.plan_value(plan("total_hours", code="DRIL"), self.events)
        self.assertEqual((values, unit), (["15.5"], "hours"))
        self.assertIn("= 15.5 (2 events on 2 dates)", text)
        self.assertEqual(len(rows), 2)

    def test_counts_dates_groups_and_depths(self):
        value = lambda *a, **k: events.plan_value(plan(*a, **k), self.events)[:2]
        self.assertEqual(value("count_events", non_productive=True), (["2"], ""))
        self.assertEqual(value("count_days", non_productive=True, min_hours_per_day=12), (["1"], ""))
        self.assertEqual(value("list_dates", non_productive=True), (["2016-08-20", "2016-08-21"], ""))
        self.assertEqual(value("first_date", code="DRIL"), (["2016-08-20"], ""))
        self.assertEqual(value("last_date", code="DRIL"), (["2016-08-22"], ""))
        self.assertEqual(value("top_group", group_by="code"), (["KICK"], ""))
        self.assertEqual(value("depth_on_date", date_from="2016-08-22"), (["300"], "ft"))
        self.assertEqual(value("depth_gain", date_from="2016-08-20", date_to="2016-08-22"), (["124"], "ft"))
        self.assertEqual(value("first_date_depth_at_least", depth_ft=150), (["2016-08-20"], ""))

    def test_no_match_gives_no_values_not_zero(self):
        self.assertEqual(events.plan_value(plan("total_hours", code="NOPE"), self.events), ([], "", "", []))
        self.assertEqual(events.plan_value(plan("not_answerable"), self.events), ([], "", "", []))
        self.assertEqual(events.plan_value(plan("total_hours", well="56-32"), self.events), ([], "", "", []))

    def test_run_plan_text_is_unchanged(self):
        for p in (plan("total_hours", code="DRIL"), plan("count_days", non_productive=True), plan("top_group")):
            self.assertEqual(events.run_plan(p, self.events), events.plan_value(p, self.events)[2:])


class AnswerOneTests(unittest.TestCase):
    def test_answer_questions_sends_the_same_requests_as_before(self):
        # The fixture was recorded from the code before answer_one was split out: the request cache and every
        # recorded run depend on these requests staying byte for byte the same.
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual((len(golden["prototype"]), len(golden["probe_multi_well"])), (31, 9))
        self.assertEqual(recorded_requests(), golden)

    def test_answer_one_scores_and_cites(self):
        by_id = {c.id: c for c in baseline.pool("three")}
        q = {"id": "live", "kind": "live", "question": "What total depth did well AK-3 reach?", "gold": []}
        recording = RecordingClient()
        row = baseline.answer_one(q, ["gdr882_ak3_eowr#c0002"], "", by_id, recording, {})
        self.assertEqual((row["status"], row["values"]), ("answered", ["1955"]))
        self.assertEqual(row["citations"][0]["chunk"], "gdr882_ak3_eowr#c0002")
        self.assertEqual((row["prompt_tokens"], len(recording.calls)), (100, 1))


if __name__ == "__main__":
    unittest.main()
