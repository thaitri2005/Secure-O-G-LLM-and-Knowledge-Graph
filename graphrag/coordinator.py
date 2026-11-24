"""The coordinator (specification §8.1, D-58, D-64): one model call frames the question, code picks the lanes.

    python -m graphrag.coordinator answer --questions prototype ak3_events --name my_pool

The model says what kind of question it is, which reports it is about and, for a question over time, the query
plan. Code reads the wells, chooses lanes from a fixed table, falls back in a fixed order, and either reports a
result computed by code or makes one answer call. The model never chooses a lane freely and never writes a query
that runs.
"""
from __future__ import annotations

from typing import Any

from .baseline import MULTI_WELL_TOKENS, answer_one, fact_sheet
from .events import PLAN_SCHEMA, PLAN_SYSTEM, code_list
from .lanes import LANES, SHEET_LINES, Engine, Evidence
from .retrieval import well_names
from .scoring import normalize, score_answer

KINDS = ("lookup", "lookup_by_date", "across_wells", "over_time", "reasoning", "other")
REPORT_TYPES = ("end_of_well", "daily", "both", "unknown")
MODES = ("allow_fallback", "exact")
# Constrained decoding writes fields in schema order (B-F22): the kind and the report type come before the plan,
# so the plan is written knowing whether the question is one over time.
FRAME_SCHEMA = {
    "type": "object",
    "properties": {"kind": {"type": "string", "enum": list(KINDS)},
                   "report_type": {"type": "string", "enum": list(REPORT_TYPES)},
                   **PLAN_SCHEMA["properties"]},
    "required": ["kind", "report_type", *PLAN_SCHEMA["properties"]],
    "additionalProperties": False,
}
FRAME_NOTE = """
Before the plan, say what the question is.
"kind":
- lookup: one value from an end-of-well report, such as "What total depth did AK-3 reach?"
- lookup_by_date: what a daily report says for one day, such as "What was the mud weight on AK-3 on 20 August 2016?"
- across_wells: compares or combines several wells, such as "Which of AK-3, 56-32 and 68-32 was drilled deepest?"
- over_time: a total, count, date or depth computed over the daily operations, such as "How many hours of non-productive time did AK-3 have in August?"
- reasoning: asks for the likely causes of a problem.
- other: anything else.
"report_type": end_of_well if an end-of-well report would hold the answer, daily if the daily drilling reports would, both, or unknown.
Use operation "not_answerable" unless kind is over_time."""
EMPTY_PLAN = {"operation": "not_answerable", "well": "", "code": "", "non_productive": False, "npt_code": "",
              "date_from": "", "date_to": "", "group_by": "", "min_hours_per_day": 0, "depth_ft": 0}


def frame_system(engine: Engine) -> str:
    return PLAN_SYSTEM + code_list(engine.events) + "\n" + FRAME_NOTE


def frame_question(question: str, engine: Engine, client) -> tuple[dict, Any]:
    """The question's frame: kind, report type and query plan. An answer that is not a frame gives the empty
    frame, which routes to the end-of-well lanes. What code reads in the question wins over what the model said."""
    call = client.chat([{"role": "system", "content": frame_system(engine)}, {"role": "user", "content": question}],
                       schema=FRAME_SCHEMA, max_tokens=260)
    parsed = call.parsed if isinstance(call.parsed, dict) else {}
    valid = (parsed.get("kind") in KINDS and parsed.get("report_type") in REPORT_TYPES
             and parsed.get("operation") in PLAN_SCHEMA["properties"]["operation"]["enum"])
    frame = {"kind": parsed["kind"], "report_type": parsed["report_type"],
             "plan": {key: parsed.get(key, empty) for key, empty in EMPTY_PLAN.items()}} if valid else \
        {"kind": "other", "report_type": "unknown", "plan": dict(EMPTY_PLAN)}
    wells = well_names(question)
    if len(wells) == 1:
        frame["plan"]["well"] = next(iter(wells))
    elif len(wells) > 1:
        frame["kind"] = "across_wells"
    return frame, call


def route(frame: dict, mode: str = "allow_fallback") -> list[str]:
    """The lanes for a frame, in order. `exact` mode leaves out passages (D-59)."""
    if frame["kind"] == "over_time" and frame["plan"]["operation"] != "not_answerable":
        lanes = ["events"]
    elif frame["report_type"] == "daily":
        lanes = ["passages"]
    else:
        # End-of-well, both, unknown, and reasoning until its lane exists (specification §8.6).
        lanes = ["well_facts", "passages"]
    return [lane for lane in lanes if mode != "exact" or lane != "passages"]


def _fallback(question: str, frame: dict, engine: Engine, routed: list[str]) -> Evidence | None:
    """Passages when no routed lane found anything: of the daily reports for a question over time or about them,
    else of the end-of-well reports."""
    daily_first = routed == ["events"] or frame["report_type"] == "daily"
    for report_type in (("daily", "end_of_well") if daily_first else ("end_of_well",)):
        found = LANES["passages"](question, dict(frame, report_type=report_type), engine)
        if not found.empty:
            return found
    return None


def _computed_row(q: dict, computed: dict, gold: dict) -> dict:
    """A result computed by code is the answer as code wrote it, cited to its source events: no model retypes it
    (specification §8.3; retyping garbled right results in E28)."""
    values = [normalize(v) for v in computed["values"]]
    sources = computed["source_chunks"]
    return {"id": q["id"], "kind": q["kind"], "status": "answered", "values": values,
            "raw_values": computed["values"], "units": [computed["unit"]] * len(values), "withheld_values": [],
            **score_answer(q, [gold[g] for g in q["gold"]], "answered", values),
            "answer_text": computed["text"], "plan": computed["plan"], "graph_result": computed["text"],
            "graph_source_chunks": sources, "citations": [{"chunk": c, "how": "event_graph"} for c in sources],
            "citations_supported": True, "passages": 0, "prompt_tokens": 0, "completion_tokens": 0, "seconds": 0.0,
            "cached": False}


def answer(q: dict, engine: Engine, frame_client, answer_client, gold: dict | None = None,
           mode: str = "allow_fallback", lane: str | None = None) -> dict:
    """One question through the coordinator. `lane` forces one lane instead of the route. The row has the keys of
    `baseline.answer_one`, plus the frame, the lanes that gave evidence, the mode, and whether it fell back."""
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}")
    gold = gold or {}
    question = q["question"]
    frame, call = frame_question(question, engine, frame_client)
    routed = [lane] if lane else route(frame, mode)
    found = [e for e in (LANES[name](question, frame, engine) for name in routed) if not e.empty]
    fallback = False
    if not found and mode == "allow_fallback":
        passages = _fallback(question, frame, engine, routed)
        found, fallback = ([passages], True) if passages else ([], False)
    by_lane = {e.lane: e for e in found}
    computed = next((e.computed for e in found if e.computed), None)
    calls = 1
    if computed:
        row = _computed_row(q, computed, gold)
    elif not found:
        # Nothing to answer from: in exact mode the graphs hold no answer, so no answer is generated.
        sources = _fallback(question, frame, engine, routed)
        row = {"id": q["id"], "kind": q["kind"], "status": "not_found_in_graph" if mode == "exact" else "not_stated",
               "values": [], "raw_values": [], "units": [], "withheld_values": [],
               **score_answer(q, [gold[g] for g in q["gold"]], "not_stated", []),
               "sources": sources.passages if sources else [], "citations": [], "citations_supported": True,
               "passages": 0, "prompt_tokens": 0, "completion_tokens": 0, "seconds": 0.0, "cached": False}
    else:
        facts, passages = by_lane.get("well_facts"), by_lane.get("passages")
        hits = passages.passages if passages else facts.passages
        answer_format = passages.answer_format if passages else facts.answer_format
        sheet = fact_sheet(facts.facts, limit=SHEET_LINES) if facts else {}
        graph = "\n".join(sheet[w] for w in sorted(well_names(question)) if w in sheet)
        row = answer_one(q, hits, graph, engine.by_id(), answer_client, gold, answer_format=answer_format,
                         max_tokens=MULTI_WELL_TOKENS if answer_format == "evidence_first" else 400)
        calls = 2
    return {**row, "frame": frame, "lanes": [e.lane for e in found], "mode": mode, "fallback": fallback,
            "computed": computed, "calls": calls, "frame_prompt_tokens": call.prompt_tokens,
            "frame_completion_tokens": call.completion_tokens, "frame_seconds": call.seconds}
