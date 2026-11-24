"""The contract with the frontend, as files: the OpenAPI description and one example response per endpoint.

    python -m backend.contract        # rewrites backend/openapi.json and backend/fixtures/*.json

Both are generated from the code, and a test fails when they fall behind it. The fixtures are real responses of the
service over committed data: the three end-of-well reports of the bundle, the event graph E28 recorded, and the
validated facts of the current design. **The model is a stand-in:** the frame and the answer of each example
question are scripted here, so the fixtures show the shape of a response and real evidence, not a model's output.
The admin examples (`admin_*`) read a small fixed log written here, not questions anyone asked.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
OPENAPI = HERE / "openapi.json"
FIXTURES = HERE / "fixtures"
# The one committed page image (scripts/make_example_page.py); it makes the page fixture carry an image_url.
EXAMPLE_PAGES = HERE.parent / "frontend/public/example-pages"

EMPTY_PLAN = {"operation": "not_answerable", "well": "", "code": "", "non_productive": False, "npt_code": "",
              "date_from": "", "date_to": "", "group_by": "", "min_hours_per_day": 0, "depth_ft": 0}
EMPTY_PROBLEM = {"date": "", "depth_ft": 0, "npt_code": "", "keywords": []}


def _cause_answer(messages: list[dict]) -> dict:
    """A stand-in's answer to the stuck-pipe prompt: it cites the evidence labels the prompt shows."""
    lines = {line.split("]")[0][1:]: line for line in messages[1]["content"].splitlines() if line.startswith("[")}
    stuck = next(label for label, line in lines.items() if "plugged inner barrel" in line)
    hot = next(label for label, line in lines.items() if "186 degrees" in line)
    return {"stated": [{"cause": "The inner barrel was plugged, which stuck the pipe",
                        "citations": [{"id": stuck, "quote": "due to plugged inner barrel"}]}],
            "possible": [{"cause": "Hot water entering the hole at shallow depth",
                          "citations": [{"id": hot, "quote": "temp. building to 186 degrees"}]}],
            "missing": ["a temperature log of the hole"]}


# name -> (request body, the frame the stand-in gives, the answer the stand-in gives)
QUESTIONS = {
    "question_cause": (
        {"question": "What caused the stuck pipe on AK-3 on 20 August 2016?"},
        {"kind": "cause", "report_type": "daily", **EMPTY_PLAN, "problem": {**EMPTY_PROBLEM, "keywords": ["stuck pipe"]}},
        _cause_answer),
    "question_cause_which": (
        {"question": "What caused the non-productive time on AK-3?"},
        {"kind": "cause", "report_type": "daily", **EMPTY_PLAN, "problem": dict(EMPTY_PROBLEM)},
        None),
    "question_end_of_well": (
        {"question": "What total depth did well AK-3 reach?"},
        {"kind": "lookup", "report_type": "end_of_well", **EMPTY_PLAN},
        {"status": "answered", "answers": [{"value": "1,955", "unit": "ft", "chunk": "c0002", "quote": "1,955 feet"}]}),
    "question_over_time": (
        {"question": "How many hours of non-productive time did AK-3 have?"},
        {"kind": "over_time", "report_type": "daily", **EMPTY_PLAN, "operation": "total_hours", "well": "AK-3",
         "non_productive": True},
        None),
    "question_not_found_exact": (
        {"question": "What total depth did well ZZ-9 reach?", "mode": "exact"},
        {"kind": "lookup", "report_type": "end_of_well", **EMPTY_PLAN},
        None),
}
READS = {
    "chunk": "/v1/chunks/gdr882_ak3_eowr%23c0002",
    "files": "/v1/files",
    "page": "/v1/files/gdr882_ak3_eowr/pages/7",
    "wells": "/v1/wells",
    "well": "/v1/wells/AK-3",
    "events": "/v1/wells/AK-3/events?date_from=2016-08-20&date_to=2016-08-20",
    "health": "/v1/health",
}


# The admin examples read a small fixed log: four questions as backend/service.py logs them, and three marks.
_ASKED = {"fixture-log-1": ("2026-11-20T08:15:00+00:00", "What total depth did well AK-3 reach?", "lookup",
                            "end_of_well", ["well_facts", "passages"], "answered", "1955 ft"),
          "fixture-log-2": ("2026-11-21T09:30:00+00:00", "How many hours of non-productive time did AK-3 have?",
                            "over_time", "daily", ["events"], "answered", "115 hours"),
          "fixture-log-3": ("2026-11-22T14:05:00+00:00", "What caused the stuck pipe on AK-3 on 20 August 2016?",
                            "cause", "daily", ["reasoning"], "answered", None),
          "fixture-log-4": ("2026-11-23T16:45:00+00:00", "What mud weight was used on well ZZ-9?", "lookup",
                            "end_of_well", [], "not_found_in_graph", None)}
_MARKS = [("fixture-log-1", "right", "", "2026-11-20T08:20:00+00:00"),
          ("fixture-log-2", "wrong", "Expected the well total of appendix 23", "2026-11-21T09:40:00+00:00"),
          ("fixture-log-2", "right", "Matches appendix 23 after checking", "2026-11-21T10:05:00+00:00")]
EXPORT_DAY = "2026-11-24"
ADMIN_READS = {
    "admin_questions": "/v1/admin/questions?limit=3",
    "admin_question": "/v1/admin/questions/fixture-log-2",
    "admin_counts": "/v1/admin/questions/counts",
    "admin_export": "/v1/admin/questions/export?ids=fixture-log-1&ids=fixture-log-4&expected_lane=end_of_well",
}


def fixture_log(path: Path):
    """The fixed log of the admin examples, written to `path` as JSON lines."""
    from .questions import JsonlQuestionLog
    lines = [{"type": "question", "id": qid, "asked_at": at, "question": question, "mode": "allow_fallback",
              "forced_lane": None, "frame": {"kind": kind, "report_type": report_type, "plan": {}}, "lanes": lanes,
              "fallback": False, "answered_from": None if not lanes else report_type, "status": status, "answers": [],
              "answer_text": text, "citations": [], "cost": {"calls": 2, "prompt_tokens": 0, "completion_tokens": 0,
                                                              "seconds": 0.0},
              "models": {"frame": "stand-in:scripted", "answer": "stand-in:scripted"}}
             for qid, (at, question, kind, report_type, lanes, status, text) in _ASKED.items()]
    lines += [{"type": "feedback", "question_id": qid, "verdict": verdict, "comment": comment, "at": at}
              for qid, verdict, comment, at in _MARKS]
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8", newline="\n")
    return JsonlQuestionLog(path)


class _Scripted:
    def __init__(self):
        self.frame, self.answer = None, None

    def chat(self, messages, schema=None, max_tokens=None):
        parsed = self.frame if "kind" in (schema or {}).get("properties", {}) else self.answer
        parsed = parsed(messages) if callable(parsed) else parsed
        return SimpleNamespace(parsed=parsed, content=json.dumps(parsed), prompt_tokens=0, completion_tokens=0,
                               seconds=0.0, cached=False)


class _NoLog:
    def add_question(self, entry: dict) -> None: ...

    def add_feedback(self, question_id: str, verdict: str, comment: str) -> None: ...

    def has_question(self, question_id: str) -> bool:
        return True

    def questions(self, filters, limit=None, offset=0) -> tuple[int, list[dict]]:
        return 0, []

    def question(self, question_id: str) -> dict | None:
        return None

    def counts(self, filters) -> dict:
        return {"questions": 0, "by_kind": {}, "by_status": {}, "by_verdict": {"right": 0, "wrong": 0, "none": 0}}


def build_openapi() -> dict:
    from .app import create_app
    return create_app().openapi()


def fixture_engine():
    """Committed data only, so the fixtures are the same on every machine: no daily-report corpus is needed."""
    from graphrag.baseline import RESULTS, pool
    from graphrag.events import Event
    from graphrag.lanes import DEFAULT_FACT_RUN, Engine
    from graphrag.validate import validate
    chunks = pool("three")
    events = [Event(**e) for e in json.loads((RESULTS / "E28_events.json").read_text(encoding="utf-8"))["events"]]
    runs = json.loads((RESULTS / f"{DEFAULT_FACT_RUN}.json").read_text(encoding="utf-8"))["fact_sheet"]
    raw = [f for name in runs for f in json.loads((RESULTS / f"{name}.json").read_text(encoding="utf-8"))["facts"]]
    facts, _ = validate(raw, {c.id: c.text for c in chunks}, strict=True)
    return Engine(chunks, [], events, facts, multi_well_retriever="perwell:bm25")


def build_fixtures() -> dict[str, object]:
    from fastapi.testclient import TestClient

    from .app import create_app
    from .service import Service
    scripted = _Scripted()
    service = Service(fixture_engine(), scripted, scripted, _NoLog(),
                      {"frame": {"endpoint": "stand-in", "model": "scripted"},
                       "answer": {"endpoint": "stand-in", "model": "scripted"}},
                      page_images=EXAMPLE_PAGES)
    client = TestClient(create_app(service))
    out: dict[str, object] = {}
    for number, (name, (body, frame, answer)) in enumerate(QUESTIONS.items(), 1):
        scripted.frame, scripted.answer = frame, answer
        service.new_id = lambda number=number: f"fixture{number:026d}"
        service.clock = lambda: 0.0
        out[name] = client.post("/v1/questions", json=body).json()
    for name, path in READS.items():
        out[name] = client.get(path).json()
    with tempfile.TemporaryDirectory() as folder:
        logged = Service(service.engine, scripted, scripted, fixture_log(Path(folder, "questions.jsonl")),
                         {"frame": {"endpoint": "stand-in", "model": "scripted"},
                          "answer": {"endpoint": "stand-in", "model": "scripted"}})
        logged.today = lambda: EXPORT_DAY
        admin = TestClient(create_app(logged))
        for name, path in ADMIN_READS.items():
            out[name] = admin.get(path).json()
    return out


def main() -> None:
    OPENAPI.write_text(json.dumps(build_openapi(), indent=2) + "\n", encoding="utf-8", newline="\n")
    FIXTURES.mkdir(exist_ok=True)
    for name, body in build_fixtures().items():
        (FIXTURES / f"{name}.json").write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OPENAPI.name} and {len(QUESTIONS) + len(READS) + len(ADMIN_READS)} fixtures")


if __name__ == "__main__":
    main()
