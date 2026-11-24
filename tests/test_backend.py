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


def entry(question_id: str, kind: str = "lookup", status: str = "answered", asked_at: str = "2026-11-24T10:00:00+00:00",
          question: str | None = None, mode: str = "allow_fallback") -> dict:
    """A log entry as backend/service.py writes it."""
    return {"id": question_id, "asked_at": asked_at, "question": question or f"Question {question_id}?",
            "mode": mode, "forced_lane": None, "frame": {"kind": kind, "report_type": "end_of_well"},
            "lanes": ["well_facts", "passages"], "fallback": False, "answered_from": "end_of_well", "status": status,
            "answers": [], "answer_text": None, "citations": [], "cost": {"calls": 2, "seconds": 1.5},
            "models": {"answer": "test:stand-in"}}


# Five logged questions over four days, and their marks: the log the admin tests read.
SEEDED = [entry("q1", "lookup", "answered", "2026-11-20T08:00:00+00:00", "What total depth did AK-3 reach?"),
          entry("q2", "over_time", "answered", "2026-11-21T09:00:00+00:00", "How many hours of NPT on AK-3?"),
          entry("q3", "cause", "ask_which", "2026-11-22T10:00:00+00:00", "What caused the NPT on AK-3?", "exact"),
          entry("q4", "lookup", "not_stated", "2026-11-22T23:30:00+00:00", "What mud weight on 56-32?"),
          entry("q5", "lookup", "answered", "2026-11-23T07:00:00+00:00", "Who drilled ak-3 for GRG?")]
MARKS = [("q1", "right", ""), ("q2", "wrong", "should be 115"), ("q2", "right", "my mistake"), ("q4", "wrong", "")]


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

    def new_log(self):
        from backend.questions import JsonlQuestionLog
        return JsonlQuestionLog(self.log_path)

    def seeded(self):
        """A client over the log of SEEDED and MARKS."""
        log = self.new_log()
        for e in SEEDED:
            log.add_question(e)
        for question_id, verdict, comment in MARKS:
            log.add_feedback(question_id, verdict, comment)
        return self.make(FRAME_EOW, DEPTH_ANSWER)

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

    def test_a_question_about_a_cause_returns_stated_and_possible_causes(self):
        frame = {"kind": "cause", "report_type": "daily", **EMPTY_PLAN,
                 "problem": {"date": "", "depth_ft": 0, "npt_code": "", "keywords": []}}
        answer = {"stated": [{"cause": "The well kicked", "citations": [{"id": "E2", "quote": "STUCK"}]}],
                  "possible": [{"cause": "Nothing shows this", "citations": [{"id": "E99", "quote": "not there"}]}],
                  "missing": ["a temperature log"]}
        body = self.make(frame, answer).post("/v1/questions", json={"question": "What caused the kick on AK-3 on 20 August 2016?"}).json()
        self.assertEqual((body["status"], body["lanes"], body["frame"]["kind"]), ("answered", ["reasoning"], "cause"))
        found = body["evidence"]["reasoning"]
        self.assertEqual(found["problem"]["npt_code"], "KICK")
        self.assertEqual(([c["cause"] for c in found["stated"]], found["possible"], found["removed"]["possible"]),
                         (["The well kicked"], [], 1))
        self.assertIn({"text": "a temperature log", "source": "model"}, found["missing"])
        self.assertTrue(body["answer_text"].startswith("Problem:"))

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

    # ---- GET /v1/files/{file_id}/pages/{n}/image ---------------------------------------------------------------

    PNG = b"\x89PNG\r\n\x1a\n" + b"stand-in image bytes"

    def with_images(self):
        from backend.app import create_app
        from backend.questions import JsonlQuestionLog
        from backend.service import Service
        root = Path(self.folder.name, "pages")
        (root / "ak3-dailyreport").mkdir(parents=True)
        (root / "ak3-dailyreport" / "p1.png").write_bytes(self.PNG)
        Path(self.folder.name, "secret.png").write_bytes(b"outside the image folder")
        roles = {"frame": {"endpoint": "test", "model": "stand-in"}, "answer": {"endpoint": "test", "model": "stand-in"}}
        service = Service(sample_engine(), ScriptedClient(FRAME_EOW, None), ScriptedClient(FRAME_EOW, None),
                          JsonlQuestionLog(self.log_path), roles, page_images=root)
        return TestClient(create_app(service))

    def test_a_page_image_is_served_and_the_page_points_to_it(self):
        client = self.with_images()
        image = client.get("/v1/files/ak3-dailyreport/pages/1/image")
        self.assertEqual((image.status_code, image.headers["content-type"], image.content), (200, "image/png", self.PNG))
        self.assertEqual(image.headers["cache-control"], "private, max-age=86400")
        self.assertEqual(client.get("/v1/files/ak3-dailyreport/pages/1").json()["image_url"],
                         "/v1/files/ak3-dailyreport/pages/1/image")
        # A page with text but no rendered image: the page is there, the link is not.
        self.assertIsNone(client.get("/v1/files/ak3-dailyreport/pages/2").json()["image_url"])
        self.assertEqual(client.get("/v1/files/ak3-dailyreport/pages/2/image").status_code, 404)

    def test_without_an_image_folder_no_page_has_an_image(self):
        client = self.make(FRAME_EOW, DEPTH_ANSWER)
        self.assertIsNone(client.get("/v1/files/ak3-dailyreport/pages/1").json()["image_url"])
        self.assertEqual(client.get("/v1/files/ak3-dailyreport/pages/1/image").status_code, 404)

    def test_the_image_route_refuses_unknown_files_bad_pages_and_path_tricks(self):
        client = self.with_images()
        for path, status in (
            ("/v1/files/nope/pages/1/image", 404),
            ("/v1/files/ak3-dailyreport/pages/0/image", 422),
            ("/v1/files/ak3-dailyreport/pages/-1/image", 422),
            ("/v1/files/ak3-dailyreport/pages/one/image", 422),
            ("/v1/files/ak3-dailyreport/pages/1.5/image", 422),
            ("/v1/files/..%2F/pages/1/image", 404),
            ("/v1/files/../pages/1/image", 404),
            ("/v1/files/%2e%2e/pages/1/image", 404),
            ("/v1/files/ak3-dailyreport%2F..%2F..%2Fsecret/pages/1/image", 404),
            ("/v1/files/..%5Cpages/pages/1/image", 404),
            ("/v1/files/ak3-dailyreport/pages/9/image", 404),
        ):
            self.assertEqual(client.get(path).status_code, status, path)

    # ---- wells and events --------------------------------------------------------------------------------------

    def test_wells_with_their_facts_documents_and_days(self):
        client = self.make(FRAME_EOW, DEPTH_ANSWER)
        self.assertEqual([w["well_id"] for w in client.get("/v1/wells").json()], ["56-32", "68-32", "AK-3"])
        well = client.get("/v1/wells/AK-3").json()
        facts = well["facts"]
        self.assertEqual(([f["property"] for f in facts["depths_and_dates"]], facts["general"], facts["readings"]),
                         (["non_productive_time"], [], []))
        npt = facts["depths_and_dates"][0]
        self.assertEqual((npt["chunk_id"], npt["file_id"], npt["value"], npt["unit"]),
                         ("gdr882_ak3_eowr#c0037", "gdr882_ak3_eowr", "115.0", "hours"))
        self.assertEqual(npt["page"], sample_engine().by_id()["gdr882_ak3_eowr#c0037"].page)
        casing, = facts["casing_strings"]
        self.assertEqual((casing["size_in"], [f["property"] for f in casing["facts"]], casing["facts"][0]["source"]),
                         ("8-5/8", ["casing_depth"], "table_mapping"))
        self.assertEqual([(d["file_id"], d["report_type"], d["pages"]) for d in well["documents"]],
                         [("gdr882_ak3_eowr", "end_of_well", 28), ("ak3-dailyreport", "daily", 3)])
        self.assertEqual(well["report_days"], [
            {"date": "2016-08-20", "hours": 10.5, "npt_hours": 1.0, "events": 2, "end_md": 176, "codes": ["DRIL", "STUCK"],
             "npt_codes": ["KICK"]},
            {"date": "2016-08-21", "hours": 24.0, "npt_hours": 24.0, "events": 1, "end_md": 176, "codes": ["KICK"],
             "npt_codes": ["KICK"]},
            {"date": "2016-08-22", "hours": 6.0, "npt_hours": 0.0, "events": 1, "end_md": 300, "codes": ["DRIL"],
             "npt_codes": []}])
        self.assertEqual(well["totals"], {"days": 3, "events": 4, "hours": 40.5, "npt_hours": 25.0,
                                          "npt_hours_by_code": {"KICK": 25.0}})
        other = client.get("/v1/wells/56-32").json()
        self.assertEqual((other["report_days"], other["totals"]["days"], other["totals"]["npt_hours_by_code"]), ([], 0, {}))
        self.assertEqual([d["file_id"] for d in other["documents"]], ["gdr1295_56-32_eowr"])
        self.assertEqual(client.get("/v1/wells/ZZ-9").status_code, 404)

    def test_a_well_page_groups_casings_largest_first_and_readings_by_depth(self):
        from backend.service import Service, inches
        self.assertEqual(sorted(["4-1/2", "20", "9-5/8", "13 3/8", "?"], key=inches, reverse=True),
                         ["20", "13 3/8", "9-5/8", "4-1/2", "?"])
        fact = lambda prop, value, **context: {"well": "AK-3", "property": prop, "value": value, "qualifier": "actual",
                                               "context": context or None, "source": "llm", "chunk_id": "x#c1",
                                               "file_id": "x", "page": 1}
        grouped = Service._grouped([
            fact("rig", "Rig 1"), fact("spud_date", "2016-08-18"), fact("total_depth", "1955"),
            fact("casing_grade", "K55", casing_size_in="4-1/2"), fact("casing_depth", "1000", casing_size_in="4-1/2"),
            fact("casing_depth", "40", casing_size_in="8-5/8"),
            fact("inclination", "1.5", depth_ft=900), fact("inclination", "0.5", depth_ft=100.0)])
        self.assertEqual([f["value"] for f in grouped["general"]], ["Rig 1"])
        self.assertEqual([f["property"] for f in grouped["depths_and_dates"]], ["total_depth", "spud_date"])
        self.assertEqual([(c["size_in"], [f["property"] for f in c["facts"]]) for c in grouped["casing_strings"]],
                         [("8-5/8", ["casing_depth"]), ("4-1/2", ["casing_depth", "casing_grade"])])
        self.assertEqual([(r["property"], [f["value"] for f in r["facts"]]) for r in grouped["readings"]],
                         [("inclination", ["0.5", "1.5"])])

    def test_a_question_about_a_cause_gives_each_event_as_fields(self):
        frame = {"kind": "cause", "report_type": "daily", **EMPTY_PLAN,
                 "problem": {"date": "", "depth_ft": 0, "npt_code": "", "keywords": []}}
        answer = {"stated": [], "possible": [], "missing": []}
        body = self.make(frame, answer).post("/v1/questions", json={"question": "What caused the kick on AK-3 on 20 August 2016?"}).json()
        evidence = body["evidence"]["reasoning"]["evidence"]
        events = [e for e in evidence if e["kind"] == "event"]
        self.assertEqual([(e["activity"]["date"], e["activity"]["code"], e["activity"]["npt_code"], e["activity"]["problem"])
                          for e in events],
                         [("2016-08-20", "DRIL", None, False), ("2016-08-20", "STUCK", "KICK", True),
                          ("2016-08-21", "KICK", "KICK", True), ("2016-08-22", "DRIL", None, False)])
        stuck = events[1]
        self.assertEqual(stuck["text"], "* 2016-08-20 17:00-18:00, 1 h, end depth 176 ft, activity STUCK, non-productive KICK: ")
        self.assertEqual({k: stuck["activity"][k] for k in ("start", "end", "hours", "end_md", "description", "chunks")},
                         {"start": "17:00", "end": "18:00", "hours": 1.0, "end_md": 176, "description": "", "chunks": ["c"]})
        self.assertTrue(all(e["activity"] is None for e in evidence if e["kind"] != "event"))

    # ---- the question log, read side (/v1/admin/) --------------------------------------------------------------

    def test_logged_questions_are_listed_newest_first_with_their_feedback(self):
        page = self.seeded().get("/v1/admin/questions").json()
        self.assertEqual((page["total"], page["limit"], page["offset"]), (5, 50, 0))
        self.assertEqual([q["id"] for q in page["questions"]], ["q5", "q4", "q3", "q2", "q1"])
        q2 = page["questions"][3]
        self.assertEqual((q2["kind"], q2["status"], q2["verdict"], q2["question"], q2["asked_at"]),
                         ("over_time", "answered", "right", "How many hours of NPT on AK-3?", "2026-11-21T09:00:00+00:00"))
        self.assertEqual([(f["verdict"], f["comment"]) for f in q2["feedback"]], [("wrong", "should be 115"), ("right", "my mistake")])
        self.assertTrue(all(f["at"] for f in q2["feedback"]))
        self.assertEqual((page["questions"][0]["verdict"], page["questions"][0]["feedback"]), (None, []))

    def test_logged_questions_are_paged_and_filtered(self):
        client = self.seeded()
        ids = lambda **params: [q["id"] for q in client.get("/v1/admin/questions", params=params).json()["questions"]]
        page = client.get("/v1/admin/questions", params={"limit": 2, "offset": 2}).json()
        self.assertEqual((page["total"], [q["id"] for q in page["questions"]]), (5, ["q3", "q2"]))
        self.assertEqual(ids(offset=9), [])
        self.assertEqual(ids(kind="lookup"), ["q5", "q4", "q1"])
        self.assertEqual(ids(status="answered"), ["q5", "q2", "q1"])
        self.assertEqual(ids(mode="exact"), ["q3"])
        self.assertEqual(ids(verdict="right"), ["q2", "q1"])     # q2's latest mark is right
        self.assertEqual(ids(verdict="wrong"), ["q4"])
        self.assertEqual(ids(verdict="none"), ["q5", "q3"])
        self.assertEqual(ids(date_from="2026-11-21", date_to="2026-11-22"), ["q4", "q3", "q2"])
        self.assertEqual(ids(date_from="2026-11-23"), ["q5"])
        self.assertEqual(ids(q="ak-3"), ["q5", "q3", "q2", "q1"])  # ignoring case
        self.assertEqual(ids(q="NPT", kind="cause"), ["q3"])
        self.assertEqual(client.get("/v1/admin/questions", params={"kind": "lookup", "limit": 1}).json()["total"], 3)
        for params in ({"limit": 0}, {"limit": 201}, {"offset": -1}, {"verdict": "maybe"}, {"date_from": "today"},
                       {"status": "fine"}, {"mode": "fast"}):
            self.assertEqual(client.get("/v1/admin/questions", params=params).status_code, 422, params)

    def test_one_logged_question_has_its_full_record(self):
        client = self.seeded()
        one = client.get("/v1/admin/questions/q2").json()
        self.assertEqual((one["id"], one["verdict"], len(one["feedback"])), ("q2", "right", 2))
        self.assertEqual({k: v for k, v in one["record"].items() if k != "asked_at"},
                         {k: v for k, v in SEEDED[1].items() if k != "asked_at"})
        self.assertEqual(client.get("/v1/admin/questions/nope").status_code, 404)

    def test_logged_questions_are_counted_by_kind_status_and_verdict(self):
        client = self.seeded()
        self.assertEqual(client.get("/v1/admin/questions/counts").json(), {
            "questions": 5, "by_kind": {"lookup": 3, "over_time": 1, "cause": 1},
            "by_status": {"answered": 3, "ask_which": 1, "not_stated": 1},
            "by_verdict": {"right": 2, "wrong": 1, "none": 2}})
        self.assertEqual(client.get("/v1/admin/questions/counts", params={"kind": "lookup"}).json()["by_verdict"],
                         {"right": 1, "wrong": 1, "none": 1})
        empty = self.make(FRAME_EOW, DEPTH_ANSWER).get("/v1/admin/questions/counts", params={"q": "nothing like this"}).json()
        self.assertEqual(empty, {"questions": 0, "by_kind": {}, "by_status": {},
                                 "by_verdict": {"right": 0, "wrong": 0, "none": 0}})

    def test_questions_asked_through_the_api_are_read_back(self):
        client = self.make(FRAME_HOURS, None)
        asked = client.post("/v1/questions", json={"question": "How many hours of drilling on AK-3?"}).json()
        client.post(f"/v1/questions/{asked['id']}/feedback", json={"verdict": "wrong", "comment": "check"})
        listed = client.get("/v1/admin/questions").json()["questions"]
        self.assertEqual([(q["id"], q["kind"], q["status"], q["answer_text"], q["verdict"]) for q in listed],
                         [(asked["id"], "over_time", "answered", asked["answer_text"], "wrong")])
        record = client.get(f"/v1/admin/questions/{asked['id']}").json()["record"]
        self.assertEqual((record["cost"], record["lanes"], record["models"]["answer"]), (asked["cost"], ["events"], "test:stand-in"))

    def test_the_admin_reads_are_never_kept_by_the_browser(self):
        client = self.seeded()
        for path in ("/v1/admin/questions", "/v1/admin/questions/q1", "/v1/admin/questions/counts",
                     "/v1/admin/questions/export"):
            self.assertEqual(client.get(path).headers.get("cache-control"), "no-store", path)

    def test_the_admin_routes_are_read_only(self):
        client = self.seeded()
        for path in ("/v1/admin/questions", "/v1/admin/questions/q1", "/v1/admin/questions/export"):
            for method in ("post", "put", "delete"):
                self.assertEqual(getattr(client, method)(path).status_code, 405, (method, path))

    def test_selected_questions_export_as_a_question_file_the_coordinator_runs(self):
        from graphrag import coordinator
        client = self.seeded()
        out = client.get("/v1/admin/questions/export", params={"kind": "lookup"})
        self.assertEqual(out.status_code, 200)
        self.assertRegex(out.headers["content-disposition"], r'^attachment; filename="collected_\d{4}-\d{2}-\d{2}\.json"$')
        body = out.json()
        self.assertRegex(body["status"], r"^COLLECTED from the application's question log on \d{4}-\d{2}-\d{2}; "
                                         r"gold answers not yet written; not expert-reviewed unless stated$")
        self.assertNotIn("expected_lane", body)
        self.assertEqual((body["facts"], body["collected"]["questions"], body["collected"]["filters"]), ([], 3, {"kind": "lookup"}))
        self.assertEqual([(q["id"], q["asked_at"], q["gold"], q["kind"]) for q in body["questions"]],
                         [("q1", "2026-11-20T08:00:00+00:00", [], "lookup"), ("q4", "2026-11-22T23:30:00+00:00", [], "lookup"),
                          ("q5", "2026-11-23T07:00:00+00:00", [], "lookup")])
        self.assertEqual(body["questions"][1]["feedback"][0]["verdict"], "wrong")
        chosen = client.get("/v1/admin/questions/export", params=[("ids", "q2"), ("ids", "q3"), ("expected_lane", "daily")]).json()
        self.assertEqual(([q["id"] for q in chosen["questions"]], chosen["expected_lane"]), (["q2", "q3"], "daily"))
        self.assertEqual(client.get("/v1/admin/questions/export", params={"expected_lane": "poetry"}).status_code, 422)
        # The file is a question file: graphrag.coordinator loads it and answers it with gold left empty.
        path = Path(self.folder.name, "collected_lookup.json")
        path.write_text(json.dumps(body), encoding="utf-8")
        name = coordinator.question_set(str(path))
        questions, gold = coordinator.pooled([name])
        self.assertEqual(([q["id"] for q in questions], gold), (["collected_lookup:q1", "collected_lookup:q4",
                                                                 "collected_lookup:q5"], {}))
        model = ScriptedClient(FRAME_EOW, DEPTH_ANSWER)
        result = coordinator.run_pool(questions, gold, sample_engine(), model, model, quiet=True)
        self.assertEqual([(r["id"], r["status"]) for r in result["rows"]],
                         [(q["id"], "answered") for q in questions])

    def test_an_empty_or_missing_log_reads_as_empty(self):
        client = self.make(FRAME_EOW, DEPTH_ANSWER)
        self.assertEqual(client.get("/v1/admin/questions").json(), {"total": 0, "limit": 50, "offset": 0, "questions": []})
        self.assertEqual(client.get("/v1/admin/questions/export").json()["questions"], [])

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
                                          "facts": 2, "wells": 3, "multi_well_retriever": "perwell:bm25",
                                          "stored_vectors": 0})
        self.assertEqual(health["models"]["answer"], "test:stand-in")

    # ---- speed ------------------------------------------------------------------------------------------------

    def test_large_answers_are_compressed_and_small_ones_are_not(self):
        # An answer with five real passages is several kilobytes; the list of wells is a few hundred bytes.
        client = self.make(FRAME_EOW, DEPTH_ANSWER)
        big = client.post("/v1/questions", json={"question": "What total depth did well AK-3 reach?"}, headers={"Accept-Encoding": "gzip"})
        self.assertEqual((big.status_code, big.headers.get("content-encoding")), (200, "gzip"))
        self.assertEqual(big.json()["answers"], [{"value": "1955", "unit": "ft"}])
        self.assertIsNone(client.get("/v1/wells", headers={"Accept-Encoding": "gzip"}).headers.get("content-encoding"))

    def test_reads_may_be_kept_briefly_by_the_browser_and_answers_never(self):
        client = self.make(FRAME_HOURS, None)
        for path in ("/v1/chunks/a", "/v1/files", "/v1/files/ak3-dailyreport/pages/1", "/v1/wells", "/v1/wells/AK-3"):
            self.assertEqual(client.get(path).headers.get("cache-control"), "private, max-age=60", path)
        asked = client.post("/v1/questions", json={"question": "How many hours of drilling on AK-3?"})
        self.assertEqual(asked.headers.get("cache-control"), "no-store")
        self.assertEqual(client.get("/v1/health").headers.get("cache-control"), "no-store")

    def test_the_question_log_knows_earlier_questions_without_rereading_the_file(self):
        from backend.questions import JsonlQuestionLog
        first = JsonlQuestionLog(self.log_path)
        first.add_question({"id": "q1", "question": "x"})
        self.assertTrue(first.has_question("q1"))
        self.log_path.rename(self.log_path.with_suffix(".moved"))          # the file is gone; the answer is remembered
        self.assertTrue(first.has_question("q1"))
        self.assertFalse(first.has_question("q2"))
        self.log_path.with_suffix(".moved").rename(self.log_path)
        self.assertTrue(JsonlQuestionLog(self.log_path).has_question("q1"))  # a new log reads what is on disk, once

    def test_the_engine_builds_its_chunk_index_once(self):
        engine = sample_engine()
        self.assertIs(engine.by_id(), engine.by_id())
        self.assertEqual(len(engine.by_id()), 372 + 5)

    def test_the_committed_contract_and_fixtures_match_the_code(self):
        from backend.contract import FIXTURES, OPENAPI, build_fixtures, build_openapi
        self.assertEqual(json.loads(OPENAPI.read_text(encoding="utf-8")), build_openapi())
        built = build_fixtures()
        self.assertEqual({p.name for p in FIXTURES.glob("*.json")}, {f"{name}.json" for name in built})
        for name, body in built.items():
            self.assertEqual(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")), body, name)


if __name__ == "__main__":
    unittest.main()
