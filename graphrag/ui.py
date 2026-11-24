"""A small local UI over Track B's answers (D-60): question, answer, cited passage, retrieved passages and, for the
event graph, the events a total was computed from.

    python -m graphrag.ui            # then open http://127.0.0.1:8765

Two modes:
- Replay: any answer run in graphrag/results/ (E19 to E28) with its questions, gold values, citations and passages.
  Needs no model and no GPU, so it works on any machine; passage text shows where the corpus is on that machine.
- Live: a new question, answered through the coordinator (graphrag/coordinator.py): one framing call, then the
  lanes code picks. Needs a reachable model endpoint, such as llama.cpp on the desktop.

Standard library only; it listens on 127.0.0.1 and reads nothing but this repository's files.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx

from .data import AK3_DAILY, AK3_DAILY_HELDOUT, AK3_EVENTS, AK3_EVENTS_HELDOUT, ROOT, load_chunks, load_questions

RESULTS = ROOT / "graphrag/results"
PAGE = Path(__file__).with_name("ui.html")
NAME = re.compile(r"^[A-Za-z0-9_.+-]{1,120}$")
# Daily-report question sets read their questions straight from the gold file: load_questions would need the corpus.
DAILY_SETS = {"ak3_daily": AK3_DAILY, "ak3_daily_heldout": AK3_DAILY_HELDOUT, "ak3_events": AK3_EVENTS,
              "ak3_events_heldout": AK3_EVENTS_HELDOUT}


# ---- data -----------------------------------------------------------------------------------------------------

@lru_cache(maxsize=1)
def chunk_index() -> dict[str, dict]:
    """Every chunk this machine has: the end-of-well bundle always, daily reports and K1 when present."""
    sources = [lambda: load_chunks()]
    try:
        from .data import appendix_chunks_path
        path = appendix_chunks_path()
        sources.append(lambda: load_chunks(path=path))
    except (FileNotFoundError, OSError, KeyError):
        pass
    try:
        from .data import k1_chunks_path
        path_k1 = k1_chunks_path()
        sources.append(lambda: load_chunks(path=path_k1))
    except (FileNotFoundError, OSError):
        pass
    out = {}
    for load in sources:
        for c in load():
            out[c.id] = {"id": c.id, "doc": c.doc_id, "page": c.page, "type": c.kind, "section": c.section,
                         "text": c.text}
    return out


def chunk_view(cid: str) -> dict:
    found = chunk_index().get(cid)
    if found:
        return found
    doc = cid.split("#", 1)[0] if "#" in cid else cid.split(":", 1)[0]
    return {"id": cid, "doc": doc, "page": None, "type": None, "section": None, "text": None}


@lru_cache(maxsize=16)
def questions_for(question_set: str) -> tuple[dict[str, dict], dict[str, dict]]:
    if question_set in DAILY_SETS:
        data = json.loads(DAILY_SETS[question_set].read_text(encoding="utf-8"))
        return {q["id"]: q for q in data["questions"]}, {f["id"]: f for f in data["facts"]}
    questions, gold = load_questions(question_set)
    return {q["id"]: q for q in questions}, gold


@lru_cache(maxsize=1)
def recorded_events() -> list:
    """The event graph as E28 built it, so replayed plans can be rerun on it without the corpus."""
    from .events import Event
    path = RESULTS / "E28_events.json"
    if not path.is_file():
        return []
    return [Event(**e) for e in json.loads(path.read_text(encoding="utf-8"))["events"]]


def method_of(run: dict) -> str:
    if "events" in run or "planner_tokens" in run:
        return "Event graph"
    if run.get("fact_sheet"):
        return "Per-well fact graph"
    if str(run.get("retriever", "")).startswith("lightrag") or "mode" in run:
        return "LightRAG"
    return "Retrieval (plain RAG)"


def list_runs() -> list[dict]:
    runs = []
    for path in sorted(RESULTS.glob("*.json")):
        if path.name.endswith(".k4.json"):
            continue
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        # A pooled coordinator run names several question sets; replaying it is the application's job.
        if isinstance(run, dict) and run.get("rows") and isinstance(run.get("question_set"), str):
            runs.append({"name": path.stem, "question_set": run["question_set"], "method": method_of(run),
                         "model": run.get("model"), "retriever": run.get("retriever"),
                         "correct": run.get("correct_total"), "questions": run.get("questions")})
    return runs


def events_view(plan: dict | None) -> list[dict]:
    """The events behind a computed result, by rerunning the recorded plan on the recorded graph (no model call)."""
    events = recorded_events()
    if not plan or not events or plan.get("operation") in (None, "not_answerable"):
        return []
    from .events import run_plan
    _, rows = run_plan(plan, events)
    return [{k: v for k, v in asdict(e).items()} for e in rows[:60]]


def run_view(name: str) -> dict:
    if not NAME.match(name) or not (RESULTS / f"{name}.json").is_file():
        raise FileNotFoundError(name)
    run = json.loads((RESULTS / f"{name}.json").read_text(encoding="utf-8"))
    questions, gold = questions_for(run["question_set"])
    rows = []
    for row in run["rows"]:
        q = questions.get(row["id"], {})
        expected = [gold[g] for g in q.get("gold", []) if g in gold]
        rows.append({
            "id": row["id"], "kind": row.get("kind"), "question": q.get("question", ""),
            "expected": [{"value": e.get("value"), "unit": e.get("unit")} for e in expected],
            "status": row.get("status"), "values": row.get("values", []), "units": row.get("units", []),
            "correct": row.get("correct"), "no_wrong_values": row.get("no_wrong_values"),
            "evidence": row.get("evidence"),
            "citations": [dict(chunk_view(c["chunk"]), how=c["how"]) for c in row.get("citations", []) if c.get("chunk")],
            "plan": row.get("plan"), "graph_result": row.get("graph_result"),
            "events": events_view(row.get("plan")) if row.get("graph_result") else [],
            "prompt_tokens": row.get("prompt_tokens"), "completion_tokens": row.get("completion_tokens"),
            "seconds": row.get("seconds")})
    return {"name": name, "method": method_of(run), "question_set": run["question_set"], "model": run.get("model"),
            "retriever": run.get("retriever"), "k": run.get("k"), "correct": run.get("correct_total"),
            "questions": run.get("questions"), "cost": run.get("cost"), "per_question": run.get("per_question"),
            "rows": rows}


# ---- live answers ---------------------------------------------------------------------------------------------

def endpoint_status(endpoint: str) -> dict:
    from .client import load_endpoints
    found = load_endpoints().get(endpoint)
    if not found:
        return {"endpoint": endpoint, "up": False, "detail": "unknown endpoint"}
    if found.hosted:
        return {"endpoint": endpoint, "up": False, "detail": "hosted endpoints are off in the UI: public data only, "
                                                             "and the live pools mix sources"}
    try:
        httpx.get(f"{found.base_url}/models", timeout=2.0).raise_for_status()
        return {"endpoint": endpoint, "up": True, "detail": found.base_url}
    except httpx.HTTPError:
        return {"endpoint": endpoint, "up": False, "detail": f"nothing answers at {found.base_url}"}


FORCED = {"eowr": ["well_facts", "passages"], "daily": ["events"]}


@lru_cache(maxsize=1)
def engine():
    """Loaded once: the reports, the event graph and the validated facts the lanes read."""
    from .lanes import Engine
    return Engine.load()


def method_of_answer(row: dict) -> str:
    if row["computed"]:
        return "Event graph"
    if row["fallback"] and row["frame"]["kind"] == "over_time":
        return "Event graph planner, then retrieval by date"
    if "well_facts" in row["lanes"]:
        return "Retrieval by well, with the per-well fact sheet" if "passages" in row["lanes"] else "Per-well fact graph"
    return "Retrieval (plain RAG)" if row["lanes"] else "Nothing found"


def ask(question: str, lane: str = "auto", mode: str = "allow_fallback") -> dict:
    """A new question, through the coordinator (specification §8.1). `lane` is "auto", or "eowr" or "daily" to force
    the end-of-well lanes or the event graph. The models are the roles file's (configs/graphrag/roles.json)."""
    question = question.strip()[:500]
    if not question:
        return {"error": "Type a question first."}
    from .client import client_for, load_roles
    from .coordinator import MODES, answer
    roles = load_roles()
    status = endpoint_status(roles["answer"]["endpoint"])
    if not status["up"]:
        return {"error": f"No model to answer with: {status['detail']}. Start llama.cpp (graphrag/README.md) or use "
                         f"replay mode."}
    q = {"id": "live", "kind": "live", "question": question, "gold": []}
    row = answer(q, engine(), client_for("frame", roles), client_for("answer", roles),
                 mode=mode if mode in MODES else "allow_fallback", lane=FORCED.get(lane))
    computed = row["computed"] or {}
    daily = row["lanes"] == ["events"] or row["frame"]["report_type"] == "daily" or row["frame"]["kind"] == "over_time"
    return {"lane": lane if lane in FORCED else "daily" if daily else "eowr", "method": method_of_answer(row),
            "question": question, "status": row["status"], "values": row["values"], "units": row["units"],
            "evidence": row.get("evidence") or row.get("answer_text"),
            "citations": [dict(chunk_view(c["chunk"]), how=c["how"]) for c in row["citations"] if c.get("chunk")],
            "plan": row["frame"]["plan"] if row["frame"]["kind"] == "over_time" else None,
            "graph_result": computed.get("text"), "events": computed.get("events", []),
            "lanes": row["lanes"], "frame": row["frame"], "mode": row["mode"], "fallback": row["fallback"],
            "prompt_tokens": row["prompt_tokens"] + row["frame_prompt_tokens"],
            "completion_tokens": row["completion_tokens"] + row["frame_completion_tokens"],
            "seconds": round(row["seconds"] + row["frame_seconds"], 3)}


# ---- HTTP -----------------------------------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, kind: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", f"{kind}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data: Any, code: int = 200) -> None:
        self._send(code, json.dumps(data).encode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802 (http.server's naming)
        path, _, query = self.path.partition("?")
        params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        try:
            if path == "/":
                self._send(200, PAGE.read_bytes(), "text/html")
            elif path == "/api/runs":
                self._json(list_runs())
            elif path == "/api/run":
                self._json(run_view(params.get("name", "")))
            elif path == "/api/status":
                self._json(endpoint_status(params.get("endpoint", "local-llama")))
            else:
                self._json({"error": "not found"}, 404)
        except FileNotFoundError:
            self._json({"error": "no such run"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/ask":
            self._json({"error": "not found"}, 404)
            return
        length = min(int(self.headers.get("Content-Length") or 0), 10_000)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            self._json(ask(str(body.get("question", "")), str(body.get("lane", "auto")),
                           str(body.get("mode", "allow_fallback"))))
        except Exception as error:  # the page shows the message instead of a blank failure
            self._json({"error": f"{type(error).__name__}: {error}"}, 500)

    def log_message(self, *args: Any) -> None:
        pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    print(f"Track B UI on http://127.0.0.1:{args.port}  (Ctrl+C to stop)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
