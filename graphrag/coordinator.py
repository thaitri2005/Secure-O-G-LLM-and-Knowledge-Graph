"""The coordinator (specification §8.1, D-58, D-64): one model call frames the question, code picks the lanes.

    python -m graphrag.coordinator answer --questions prototype ak3_events --name my_pool

The model says what kind of question it is, which reports it is about and, for a question over time, the query
plan. Code reads the wells, chooses lanes from a fixed table, falls back in a fixed order, and either reports a
result computed by code or makes one answer call. The model never chooses a lane freely and never writes a query
that runs.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

from .baseline import MULTI_WELL_TOKENS, RESULTS, answer_one, fact_sheet
from .client import client_for, load_roles
from .data import QUESTION_SETS, ROOT, load_questions
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
    # A hosted endpoint may not enforce the schema, so the plan's field types are checked here too.
    typed = all(type(parsed.get(key, empty)) in ((int, float) if type(empty) is int else (type(empty),))
                for key, empty in EMPTY_PLAN.items())
    valid = (typed and parsed.get("kind") in KINDS and parsed.get("report_type") in REPORT_TYPES
             and parsed.get("operation") in PLAN_SCHEMA["properties"]["operation"]["enum"]
             and parsed.get("group_by", "") in PLAN_SCHEMA["properties"]["group_by"]["enum"])
    frame = {"kind": parsed["kind"], "report_type": parsed["report_type"],
             "plan": {key: parsed.get(key, empty) for key, empty in EMPTY_PLAN.items()}} if valid else \
        {"kind": "other", "report_type": "unknown", "plan": dict(EMPTY_PLAN)}
    wells = well_names(question) & engine.wells
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


def _row_without_a_call(q: dict, gold: dict, status: str, values: list[str], raw: list[str], units: list[str],
                        citations: list[dict]) -> dict:
    """A row no answer call was made for, with every key `baseline.answer_one` gives, so that a run's rows can be
    summarized and compared whichever way each was answered. The checks on a model's citations do not apply."""
    expected = [gold[g] for g in q["gold"]]
    return {"id": q["id"], "kind": q["kind"], "status": status, "values": values, "raw_values": raw, "units": units,
            "withheld_values": [], **score_answer(q, expected, "answered" if values else "not_stated", values),
            "retrieved_gold": None, "gold_facts_retrieved": None, "gold_facts": len(expected), "citations": citations,
            "citations_supported": True, "verified_on_gold_chunk": None, "citations_in_retrieved": True,
            "citations_on_gold_chunk": None, "quotes_verbatim": True, "passages": 0, "prompt_tokens": 0,
            "completion_tokens": 0, "seconds": 0.0, "cached": False}


def _computed_row(q: dict, computed: dict, gold: dict) -> dict:
    """A result computed by code is the answer as code wrote it, cited to its source events: no model retypes it
    (specification §8.3; retyping garbled right results in E28)."""
    values = list(dict.fromkeys(normalize(v) for v in computed["values"]))
    sources = computed["source_chunks"]
    row = _row_without_a_call(q, gold, "answered", values, computed["values"], [computed["unit"]] * len(values),
                              [{"chunk": c, "how": "event_graph"} for c in sources])
    return {**row, "answer_text": computed["text"], "plan": computed["plan"], "graph_result": computed["text"],
            "graph_source_chunks": sources}


def answer(q: dict, engine: Engine, frame_client, answer_client, gold: dict | None = None,
           mode: str = "allow_fallback", lane: str | list[str] | None = None) -> dict:
    """One question through the coordinator. `lane` forces one lane, or several, instead of the route. The row has the keys of
    `baseline.answer_one`, plus the frame, the lanes that gave evidence, the mode, and whether it fell back."""
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}")
    gold = gold or {}
    question = q["question"]
    frame, call = frame_question(question, engine, frame_client)
    routed = ([lane] if isinstance(lane, str) else list(lane)) if lane else route(frame, mode)
    if mode == "exact":
        routed = [name for name in routed if name != "passages"]
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
        sources = _fallback(question, frame, engine, routed) if mode == "exact" else None
        row = {**_row_without_a_call(q, gold, "not_found_in_graph" if mode == "exact" else "not_stated", [], [], [], []),
               "sources": sources.passages if sources else []}
    else:
        facts, passages = by_lane.get("well_facts"), by_lane.get("passages")
        hits = passages.passages if passages else facts.passages
        answer_format = passages.answer_format if passages else facts.answer_format
        sheet = fact_sheet(facts.facts, limit=SHEET_LINES) if facts else {}
        graph = "\n".join(sheet[w] for w in sorted(well_names(question)) if w in sheet)
        row = answer_one(q, hits, graph, engine.by_id(), answer_client, gold, answer_format=answer_format,
                         max_tokens=MULTI_WELL_TOKENS if answer_format == "evidence_first" else 400)
        calls = 2
    # The reports the evidence came from: a daily question can fall back to end-of-well passages, and must say so.
    answered_from = next((e.report_type for e in found if e.lane != "well_facts"), "end_of_well") if found else None
    return {**row, "frame": frame, "lanes": [e.lane for e in found], "mode": mode, "fallback": fallback,
            "answered_from": answered_from,
            "computed": computed, "calls": calls, "frame_prompt_tokens": call.prompt_tokens,
            "frame_completion_tokens": call.completion_tokens, "frame_seconds": call.seconds}


# ---- pooled runs: every question set in one pool, with no lane given (E33) --------------------------------------

# The lane each set was answered by when the lane was chosen by hand (specification §8.4). It is what the
# coordinator's choice is judged against; it is not shown to the coordinator.
EXPECTED = {"prototype": "end_of_well", "probe": "end_of_well", "simulated": "end_of_well", "heldout": "end_of_well",
            "ak3_daily": "daily", "ak3_daily_heldout": "daily", "ak3_events": "events", "ak3_events_heldout": "events"}


def pooled(sets: list[str]) -> tuple[list[dict], dict[str, dict]]:
    """The questions and gold of several sets as one pool. IDs gain their set's name, since sets reuse them."""
    questions, gold = [], {}
    for name in sets:
        set_questions, set_gold = load_questions(name)
        gold.update({f"{name}:{key}": fact for key, fact in set_gold.items()})
        questions += [dict(q, id=f"{name}:{q['id']}", gold=[f"{name}:{g}" for g in q["gold"]], set=name,
                           expected=EXPECTED[name]) for q in set_questions]
    return questions, gold


def rightly_routed(row: dict) -> bool:
    """Whether the coordinator sent a question where its set was answered from by hand."""
    daily = row["frame"]["report_type"] == "daily"
    if row["expected"] == "events":
        return row["lanes"] == ["events"]
    if row["expected"] == "daily":
        return daily
    return not daily and "events" not in row["lanes"]


def summarize_pool(rows: list[dict]) -> dict:
    def part(subset: list[dict]) -> dict:
        count = lambda key: f"{sum(bool(r[key]) for r in subset)}/{len(subset)}"
        mean = lambda keys: round(sum(r[k] for r in subset for k in keys) / len(subset), 1)
        return {"questions": len(subset), "correct": count("correct"), "rightly_routed": count("rightly_routed"),
                "fallbacks": sum(bool(r["fallback"]) for r in subset), "calls_per_question": mean(["calls"]),
                "prompt_tokens": mean(["prompt_tokens", "frame_prompt_tokens"]),
                "completion_tokens": mean(["completion_tokens", "frame_completion_tokens"]),
                "seconds": mean(["seconds", "frame_seconds"])}

    whole = part(rows)
    return {"questions": whole["questions"], "correct_total": whole["correct"], "rightly_routed": whole["rightly_routed"],
            "fallbacks": whole["fallbacks"],
            "per_question": {k: whole[k] for k in ("calls_per_question", "prompt_tokens", "completion_tokens", "seconds")},
            "by_set": {name: part([r for r in rows if r["set"] == name]) for name in dict.fromkeys(r["set"] for r in rows)}}


def check_engine(engine: Engine, sets: list[str]) -> None:
    """Stops a run that would answer daily-report questions without the daily reports: every such question would
    fall back to end-of-well passages and the scores would mean nothing."""
    needing = [name for name in sets if EXPECTED[name] in ("daily", "events")]
    if needing and not engine.has_daily:
        raise SystemExit(f"The daily-report corpus is not on this machine, and {', '.join(needing)} need it. "
                         f"Regenerate it (docs/tracks/B-graphrag/next-runs.md) or unzip a K1 package and use --k1.")


def run_pool(questions: list[dict], gold: dict, engine: Engine, frame_client, answer_client,
             mode: str = "allow_fallback", quiet: bool = False) -> dict:
    rows = []
    for q in questions:
        row = answer(q, engine, frame_client, answer_client, gold, mode)
        row.update(set=q["set"], expected=q["expected"])
        row["rightly_routed"] = rightly_routed(row)
        rows.append(row)
        if not quiet:
            print(f"{q['id']:<28} {'OK ' if row['correct'] else 'BAD'} {'route ok ' if row['rightly_routed'] else 'MISROUTED'} "
                  f"{'+'.join(row['lanes']) or '-':<20} {row['status']} {row['values']}", flush=True)
    return {**summarize_pool(rows), "rows": rows}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("answer")
    a.add_argument("--questions", nargs="+", choices=QUESTION_SETS, required=True)
    a.add_argument("--mode", choices=MODES, default="allow_fallback")
    a.add_argument("--k1", action="store_true", help="daily reports and events from Track A's K1 version 1 package")
    a.add_argument("--no-embeddings", action="store_true",
                   help="questions naming several wells use per-well BM25, for a machine without the embedding server")
    a.add_argument("--name", required=True, help="result file name under graphrag/results/")
    args = parser.parse_args(argv)
    engine = Engine.load(k1=args.k1, **({"multi_well_retriever": "perwell:bm25"} if args.no_embeddings else {}))
    check_engine(engine, args.questions)
    roles = load_roles()
    frame_client, answer_client = client_for("frame", roles), client_for("answer", roles)
    questions, gold = pooled(args.questions)
    result = run_pool(questions, gold, engine, frame_client, answer_client, args.mode)
    out = {"question_set": args.questions, "mode": args.mode, "roles": {r: roles[r] for r in ("frame", "answer")},
           "retriever": "coordinator", "pool": "k1" if args.k1 else "bundle and corpus release",
           "multi_well_retriever": engine.multi_well_retriever, "events": len(engine.events), "facts": len(engine.facts),
           "cost": {"frame": frame_client.ledger.summary(), "answer": answer_client.ledger.summary()}, **result}
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{args.name}.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=2))
    print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
