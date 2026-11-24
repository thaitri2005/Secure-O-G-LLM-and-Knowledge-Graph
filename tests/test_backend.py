"""The read-path API (specification §7.5), over a small engine and stand-in models: no server, store or GPU needed."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

try:
    from fastapi.testclient import TestClient
except ImportError:  # the backend's packages are in backend/requirements.txt, not in the main lock file
    TestClient = None

from graphrag import baseline, lanes
from graphrag.data import Chunk
from graphrag.events import Event

DEPTH_ANSWER = {"evidence": "The report states the depth.", "status": "answered",
                "answers": [{"value": "1,955", "unit": "ft", "chunk": "c0002", "quote": "1,955 feet"}]}
EMPTY_PLAN = {"operation": "not_answerable", "well": "", "code": "", "non_productive": False, "npt_code": "",
              "date_from": "", "date_to": "", "group_by": "", "min_hours_per_day": 0, "depth_ft": 0}
FRAME_EOW = {"kind": "lookup", "report_type": "end_of_well", **EMPTY_PLAN}
FRAME_HOURS = {"kind": "over_time", "report_type": "daily", **EMPTY_PLAN, "operation": "total_hours", "well": "AK-3",
               "code": "DRIL"}
FACTS = [
    {"chunk": "gdr882_ak3_eowr#c0013", "well": "AK-3", "property": "casing_depth", "qualifier": "actual",
     "context": {"casing_size_in": "8-5/8"}, "value": "40", "source": "gdr882_ak3_eowr#t003"},
    {"chunk": "gdr882_ak3_eowr#c0037", "well": "AK-3", "property": "non_productive_time", "qualifier": "actual",
     "context": None, "value": "115.0", "unit": "hours"},
]


class ScriptedClient:
    """Returns `frame` to a framing call and `answer` to an answer call."""

    def __init__(self, frame, answer, fail=False):
        self.frame, self.answer, self.fail = frame, answer, fail

    def chat(self, messages, schema=None, max_tokens=None):
        if self.fail:
            import httpx
            raise httpx.ConnectError("nothing answers")
        parsed = self.frame if "kind" in (schema or {}).get("properties", {}) else self.answer
        return SimpleNamespace(parsed=parsed, content=json.dumps(parsed), prompt_tokens=100, completion_tokens=20,
                               seconds=0.1, cached=False)


def sample_engine():
    daily = [Chunk(name, "ak3-dailyreport", page, "text", "Operations", f"Report For 2{page - 1}-Aug-16 AK-3 {name}")
             for name, page in (("a", 1), ("b", 1), ("c", 1), ("d", 2), ("e", 3))]
    events = [Event("2016-08-20", "0:00", "9:30", 9.5, 100, "DRIL", "drilling ahead", ["a"]),
              Event("2016-08-20", "17:00", "18:00", 1.0, 176, "STUCK", "", ["c"], "KICK"),
              Event("2016-08-21", "0:00", "0:00", 24.0, 176, "KICK", "", ["d"], "KICK"),
              Event("2016-08-22", "0:00", "6:00", 6.0, 300, "DRIL", "", ["e", "a"])]
    return lanes.Engine(baseline.pool("three"), daily, events, FACTS, multi_well_retriever="perwell:bm25")


@unittest.skipIf(TestClient is None, "needs backend/requirements.txt (fastapi)")
class BackendTests(unittest.TestCase):
    def setUp(self):
        from backend.app import create_app
        from backend.questions import JsonlQuestionLog
        from backend.service import Service
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.log_path = Path(self.folder.name, "questions.jsonl")
        self.make = lambda frame, answer, fail=False: TestClient(create_app(Service(
            sample_engine(), ScriptedClient(frame, answer, fail), ScriptedClient(frame, answer, fail),
            JsonlQuestionLog(self.log_path), roles={"frame": {"endpoint": "test", "model": "stand-in"},
                                                    "answer": {"endpoint": "test", "model": "stand-in"}})))

    def log(self):
        return [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()]

    # ---- POST /v1/questions ------------------------------------------------------------------------------------

    def test_an_end_of_well_question_returns_a_cited_answer_and_its_evidence(self):
        out = self.make(FRAME_EOW, DEPTH_ANSWER).post("/v1/questions", json={"question": "What total depth did well AK-3 reach?"})
        self.assertEqual(out.status_code, 200)
        body = out.json()
        self.assertEqual((body["status"], body["mode"], body["lanes"]), ("answered", "allow_fallback", ["well_facts", "passages"]))
        self.assertEqual(body["answers"], [{"value": "1955", "unit": "ft"}])
        self.assertEqual(body["answered_from"], "end_of_well")
        self.assertEqual(body["frame"]["kind"], "lookup")
        citation = body["citations"][0]
        self.assertEqual((citation["file_id"], citation["how"] in ("model", "by_quote", "by_value")), ("gdr882_ak3_eowr", True))
        self.assertIn("1,955", citation["text"])
        self.assertIsInstance(citation["page"], int)
        self.assertEqual(len(body["evidence"]["passages"]), 5)
        self.assertEqual({f["property"] for f in body["evidence"]["facts"]}, {"casing_depth", "non_productive_time"})
        self.assertIsNone(body["evidence"]["computed"])
        self.assertEqual(body["cost"]["calls"], 2)
        self.assertEqual(body["cost"]["prompt_tokens"], 200)

    def test_a_question_over_time_returns_the_computed_result_and_its_events(self):
        body = self.make(FRAME_HOURS, None).post("/v1/questions", json={"question": "How many hours of drilling on AK-3?"}).json()
        self.assertEqual((body["status"], body["lanes"], body["answered_from"]), ("answered", ["events"], "daily"))
        self.assertEqual(body["answers"], [{"value": "15.5", "unit": "hours"}])
        self.assertEqual(body["answer_text"], "total hours for code DRIL = 15.5 (2 events on 2 dates)")
        computed = body["evidence"]["computed"]
        self.assertEqual((computed["plan"]["operation"], len(computed["events"])), ("total_hours", 2))
        self.assertEqual(computed["events"][0]["code"], "DRIL")
        self.assertEqual([c["how"] for c in body["citations"]], ["event_graph", "event_graph"])
        self.assertEqual(body["cost"]["calls"], 1)

    def test_exact_mode_with_nothing_in_the_graph_is_not_found(self):
        body = self.make(FRAME_EOW, DEPTH_ANSWER).post("/v1/questions", json={"question": "What depth did ZZ-9 reach?", "mode": "exact"}).json()
        self.assertEqual((body["status"], body["answers"], body["lanes"], body["mode"]), ("not_found_in_graph", [], [], "exact"))
        self.assertGreater(len(body["evidence"]["passages"]), 0)  # the closest passages, shown as sources only

    def test_a_lane_can_be_forced(self):
        body = self.make(FRAME_HOURS, DEPTH_ANSWER).post("/v1/questions", json={"question": "What total depth did well AK-3 reach?", "lane": "passages"}).json()
        self.assertEqual(body["lanes"], ["passages"])

    def test_bad_requests_are_refused(self):
        client = self.make(FRAME_EOW, DEPTH_ANSWER)
        for body in ({"question": ""}, {"question": "x" * 501}, {"question": "ok", "mode": "fast"},
                     {"question": "ok", "lane": "poetry"}, {}):
            self.assertEqual(client.post("/v1/questions", json=body).status_code, 422, body)

    def test_a_model_that_does_not_answer_is_a_503_not_a_crash(self):
        out = self.make(FRAME_EOW, DEPTH_ANSWER, fail=True).post("/v1/questions", json={"question": "What depth did AK-3 reach?"})
        self.assertEqual(out.status_code, 503)
        self.assertIn("model", out.json()["detail"])

    # ---- the question log and feedback -------------------------------------------------------------------------

    def test_every_question_is_logged_with_its_lane_and_answer(self):
        client = self.make(FRAME_HOURS, None)
        body = client.post("/v1/questions", json={"question": "How many hours of drilling on AK-3?"}).json()
        entry = self.log()[0]
        self.assertEqual((entry["type"], entry["id"], entry["question"]), ("question", body["id"], "How many hours of drilling on AK-3?"))
        self.assertEqual((entry["lanes"], entry["status"], entry["answers"]), (["events"], "answered", [{"value": "15.5", "unit": "hours"}]))
        self.assertEqual(entry["models"]["answer"], "test:stand-in")
        self.assertIn("asked_at", entry)

    def test_feedback_is_stored_against_its_question(self):
        client = self.make(FRAME_HOURS, None)
        asked = client.post("/v1/questions", json={"question": "How many hours of drilling on AK-3?"}).json()
        out = client.post(f"/v1/questions/{asked['id']}/feedback", json={"verdict": "wrong", "comment": "should be 16"})
        self.assertEqual(out.status_code, 200)
        entry = self.log()[1]
        self.assertEqual((entry["type"], entry["question_id"], entry["verdict"], entry["comment"]),
                         ("feedback", asked["id"], "wrong", "should be 16"))

    def test_feedback_on_an_unknown_question_or_with_a_bad_verdict_is_refused(self):
        client = self.make(FRAME_HOURS, None)
        self.assertEqual(client.post("/v1/questions/nope/feedback", json={"verdict": "wrong"}).status_code, 404)
        asked = client.post("/v1/questions", json={"question": "How many hours of drilling on AK-3?"}).json()
        self.assertEqual(client.post(f"/v1/questions/{asked['id']}/feedback", json={"verdict": "meh"}).status_code, 422)

    # ---- sources -----------------------------------------------------------------------------------------------

    def test_a_chunk_is_read_by_its_id_in_either_format(self):
        client = self.make(FRAME_EOW, DEPTH_ANSWER)
        chunk = client.get("/v1/chunks/gdr882_ak3_eowr%23c0002").json()
        self.assertEqual((chunk["chunk_id"], chunk["file_id"]), ("gdr882_ak3_eowr#c0002", "gdr882_ak3_eowr"))
        self.assertIn("1,955", chunk["text"])
        self.assertEqual(client.get("/v1/chunks/a").json()["file_id"], "ak3-dailyreport")
        self.assertEqual(client.get("/v1/chunks/nope").status_code, 404)

    def test_files_and_their_pages(self):
        client = self.make(FRAME_EOW, DEPTH_ANSWER)
        files = {f["file_id"]: f for f in client.get("/v1/files").json()}
        self.assertEqual(set(files), {"gdr882_ak3_eowr", "gdr1295_56-32_eowr", "gdr1153_68-32_eowr", "ak3-dailyreport"})
        self.assertEqual((files["ak3-dailyreport"]["report_type"], files["ak3-dailyreport"]["pages"]), ("daily", 3))
        self.assertEqual(files["gdr882_ak3_eowr"]["report_type"], "end_of_well")
        page = client.get("/v1/files/ak3-dailyreport/pages/1").json()
        self.assertEqual(([c["chunk_id"] for c in page["chunks"]], page["page"]), (["a", "b", "c"], 1))
        self.assertEqual(client.get("/v1/files/ak3-dailyreport/pages/9").status_code, 404)
        self.assertEqual(client.get("/v1/files/nope/pages/1").status_code, 404)

    # ---- wells and events --------------------------------------------------------------------------------------

    def test_wells_with_their_facts_documents_and_days(self):
        client = self.make(FRAME_EOW, DEPTH_ANSWER)
        self.assertEqual([w["well_id"] for w in client.get("/v1/wells").json()], ["56-32", "68-32", "AK-3"])
        well = client.get("/v1/wells/AK-3").json()
        self.assertEqual(len(well["facts"]), 2)
        self.assertEqual(well["facts"][0]["chunk_id"], "gdr882_ak3_eowr#c0037")
        self.assertIn("gdr882_ak3_eowr", well["documents"])
        self.assertEqual(well["report_days"], ["2016-08-20", "2016-08-21", "2016-08-22"])
        self.assertEqual(client.get("/v1/wells/56-32").json()["report_days"], [])
        self.assertEqual(client.get("/v1/wells/ZZ-9").status_code, 404)

    def test_events_of_a_well_between_two_dates(self):
        client = self.make(FRAME_EOW, DEPTH_ANSWER)
        events = client.get("/v1/wells/AK-3/events", params={"date_from": "2016-08-21", "date_to": "2016-08-22"}).json()
        self.assertEqual([(e["date"], e["code"], e["npt_code"]) for e in events], [("2016-08-21", "KICK", "KICK"), ("2016-08-22", "DRIL", None)])
        self.assertEqual(len(client.get("/v1/wells/AK-3/events").json()), 4)
        self.assertEqual(client.get("/v1/wells/56-32/events").json(), [])
        self.assertEqual(client.get("/v1/wells/AK-3/events", params={"date_from": "August"}).status_code, 422)

    # ---- health and the contract -------------------------------------------------------------------------------

    def test_health_says_what_is_loaded_and_which_models_serve(self):
        health = self.make(FRAME_EOW, DEPTH_ANSWER).get("/v1/health").json()
        self.assertEqual(health["data"], {"source": "files", "end_of_well_chunks": 372, "daily_chunks": 5, "events": 4,
                                          "facts": 2, "wells": 3})
        self.assertEqual(health["models"]["answer"], "test:stand-in")

    def test_the_committed_contract_and_fixtures_match_the_code(self):
        from backend.contract import FIXTURES, OPENAPI, build_fixtures, build_openapi
        self.assertEqual(json.loads(OPENAPI.read_text(encoding="utf-8")), build_openapi())
        built = build_fixtures()
        self.assertEqual({p.name for p in FIXTURES.glob("*.json")}, {f"{name}.json" for name in built})
        for name, body in built.items():
            self.assertEqual(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")), body, name)


if __name__ == "__main__":
    unittest.main()
