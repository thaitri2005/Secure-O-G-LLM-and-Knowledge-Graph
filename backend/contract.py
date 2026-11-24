"""The contract with the frontend, as files: the OpenAPI description and one example response per endpoint.

    python -m backend.contract        # rewrites backend/openapi.json and backend/fixtures/*.json

Both are generated from the code, and a test fails when they fall behind it. The fixtures are real responses of the
service over committed data: the three end-of-well reports of the bundle, the event graph E28 recorded, and the
validated facts of the current design. **The model is a stand-in:** the frame and the answer of each example
question are scripted here, so the fixtures show the shape of a response and real evidence, not a model's output.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
OPENAPI = HERE / "openapi.json"
FIXTURES = HERE / "fixtures"
# The one committed page image (scripts/make_example_page.py); it makes the page fixture carry an image_url.
EXAMPLE_PAGES = HERE.parent / "frontend/public/example-pages"

EMPTY_PLAN = {"operation": "not_answerable", "well": "", "code": "", "non_productive": False, "npt_code": "",
              "date_from": "", "date_to": "", "group_by": "", "min_hours_per_day": 0, "depth_ft": 0}
# name -> (request body, the frame the stand-in gives, the answer the stand-in gives)
QUESTIONS = {
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
    "page": "/v1/files/gdr882_ak3_eowr/pages/2",
    "wells": "/v1/wells",
    "well": "/v1/wells/AK-3",
    "events": "/v1/wells/AK-3/events?date_from=2016-08-20&date_to=2016-08-20",
    "health": "/v1/health",
}


class _Scripted:
    def __init__(self):
        self.frame, self.answer = None, None

    def chat(self, messages, schema=None, max_tokens=None):
        parsed = self.frame if "kind" in (schema or {}).get("properties", {}) else self.answer
        return SimpleNamespace(parsed=parsed, content=json.dumps(parsed), prompt_tokens=0, completion_tokens=0,
                               seconds=0.0, cached=False)


class _NoLog:
    def add_question(self, entry: dict) -> None: ...

    def add_feedback(self, question_id: str, verdict: str, comment: str) -> None: ...

    def has_question(self, question_id: str) -> bool:
        return True


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
        out[name] = client.post("/v1/questions", json=body).json()
    for name, path in READS.items():
        out[name] = client.get(path).json()
    return out


def main() -> None:
    OPENAPI.write_text(json.dumps(build_openapi(), indent=2) + "\n", encoding="utf-8", newline="\n")
    FIXTURES.mkdir(exist_ok=True)
    for name, body in build_fixtures().items():
        (FIXTURES / f"{name}.json").write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OPENAPI.name} and {len(QUESTIONS) + len(READS)} fixtures")


if __name__ == "__main__":
    main()
