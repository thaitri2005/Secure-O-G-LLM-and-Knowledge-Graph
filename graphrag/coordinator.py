"""The coordinator (specification §8.1, D-58, D-64): one model call frames the question, code picks the lanes.

    python -m graphrag.coordinator answer --questions prototype ak3_events --name my_pool
    python -m graphrag.coordinator answer --questions graphrag/gold/<question file>.json --name my_probe

The model says what kind of question it is, which reports it is about and, for a question over time, the query
plan; for a question about causes, the problem it is about. Code reads the wells and dates, chooses lanes from a
fixed table, falls back in a fixed order, and either reports a result computed by code or makes one answer call.
The model never chooses a lane freely and never writes a query that runs.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from . import reasoning
from .baseline import MULTI_WELL_TOKENS, RESULTS, answer_one, fact_sheet
from .client import client_for, load_roles
from .data import QUESTION_SETS, ROOT, load_questions
from .events import PLAN_SCHEMA, PLAN_SYSTEM, code_list
from .lanes import LANES, SHEET_LINES, Engine, Evidence, shown_facts
from .reasoning import EMPTY_PROBLEM
from .retrieval import question_dates, well_names
from .scoring import normalize, score_answer

KINDS = ("lookup", "lookup_by_date", "across_wells", "over_time", "cause", "other")
REPORT_TYPES = ("end_of_well", "daily", "both", "unknown")
MODES = ("allow_fallback", "exact")
# The problem a question about causes is about, for the reasoning lane (specification §8.6, step 1).
PROBLEM_SCHEMA = {
    "type": "object",
    "properties": {"date": {"type": "string"}, "depth_ft": {"type": "number"}, "npt_code": {"type": "string"},
                   "keywords": {"type": "array", "maxItems": 3, "items": {"type": "string"}}},
    "required": ["date", "depth_ft", "npt_code", "keywords"],
    "additionalProperties": False,
}
# Constrained decoding writes fields in schema order (B-F22): the kind and the report type come before the plan,
# so the plan is written knowing whether the question is one over time; the problem comes last.
FRAME_SCHEMA = {
    "type": "object",
    "properties": {"kind": {"type": "string", "enum": list(KINDS)},
                   "report_type": {"type": "string", "enum": list(REPORT_TYPES)},
                   **PLAN_SCHEMA["properties"], "problem": PROBLEM_SCHEMA},
    "required": ["kind", "report_type", *PLAN_SCHEMA["properties"], "problem"],
    "additionalProperties": False,
}
FRAME_NOTE = """
Before the plan, say what the question is.
"kind":
- lookup: one value from an end-of-well report, such as "What total depth did AK-3 reach?"
- lookup_by_date: what a daily report says for one day, such as "What was the mud weight on AK-3 on 20 August 2016?"
- across_wells: compares or combines several wells, such as "Which of AK-3, 56-32 and 68-32 was drilled deepest?"
- over_time: a total, count, date or depth computed over the daily operations, such as "How many hours of non-productive time did AK-3 have in August?"
- cause: asks why a problem happened or what its likely causes were, such as "AK-3 lost time on 21 August 2016. What are the likely causes?"
- other: anything else.
"report_type": end_of_well if an end-of-well report would hold the answer, daily if the daily drilling reports would, both, or unknown.
Use operation "not_answerable" unless kind is over_time.
"problem", for kind cause only: "date" (YYYY-MM-DD) and "depth_ft" if the question gives them, "npt_code" if it names a non-productive code, and "keywords": up to three words from the question that name the problem, such as "stuck pipe", "kick" or "weather", not general words such as "problem" or "lost time". For other kinds use "", 0, "" and [].
Non-productive codes in these reports: """
EMPTY_PLAN = {"operation": "not_answerable", "well": "", "code": "", "non_productive": False, "npt_code": "",
              "date_from": "", "date_to": "", "group_by": "", "min_hours_per_day": 0, "depth_ft": 0}


def frame_system(engine: Engine) -> str:
    npt_codes = sorted({e.npt_code for e in engine.events if e.npt_code})
    return PLAN_SYSTEM + code_list(engine.events) + "\n" + FRAME_NOTE + (", ".join(npt_codes) or "none") + "."


def _of_type(value: Any, empty: Any) -> bool:
    """`value` has the type of the empty field: a number for a number (not a boolean), else the same type."""
    return type(value) in ((int, float) if type(empty) is int else (type(empty),))


def _problem(parsed: dict) -> dict | None:
    """The frame's problem with its field types checked, or None when a field has the wrong type. A frame without
    one has the empty problem; at most three keywords are kept."""
    problem = parsed.get("problem", EMPTY_PROBLEM)
    if not isinstance(problem, dict) or not all(_of_type(problem.get(key, empty), empty)
                                                for key, empty in EMPTY_PROBLEM.items()):
        return None
    if not all(isinstance(k, str) for k in problem.get("keywords", [])):
        return None
    out = {key: problem.get(key, empty) for key, empty in EMPTY_PROBLEM.items()}
    out["keywords"] = [k.strip() for k in out["keywords"] if k.strip()][:3]
    return out


# Names the well pattern also matches: casing grades (K-55, L-80, P-110), tools and tests (BHA-3, DST-1).
NOT_A_WELL = re.compile(r"(?:[HJKLNPCTQ]-\d{2,3}|(?:BHA|DST|RFT|MDT|LOT|FIT|API|ISO|PDC|BOP|BIT|RUN)-\d+[A-Z]?)")
_MONTH_WORDS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def _date_said(day: str, question: str) -> bool:
    """Whether a question (lower case) shows the model's ISO day in a form `question_dates` does not read, such as
    "20 August" with no year: the day's number and the month's name are both in it."""
    found = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", day)
    if not found or not 1 <= int(found.group(2)) <= 12:
        return False
    return bool(re.search(rf"(?<!\d)0?{int(found.group(3))}(?!\d)", question)) and _MONTH_WORDS[int(found.group(2)) - 1] in question


# Words a model wrote into a plan's `code` that are the schema's own field names, not codes of any report.
NOT_A_CODE = {"activity_code", "npt_code", "code", "non_productive", "nonproductive", "none", "any", "all"}
SAYS_NON_PRODUCTIVE = re.compile(r"non[- ]?productive|\bnpt\b|lost time|down ?time", re.IGNORECASE)


def _check_plan(frame: dict, question: str, dates: set[str], engine: Engine) -> None:
    """Checks the plan of a frame against the question, in place (E33, B-F79). One framing call writes sloppier
    plans than the dedicated planner did: on 58 event questions it invented a non-productive code for "non-productive
    time", wrote a field's name where a code belongs, put the year 2020 or 2023 on dates the question gave in 2016,
    and called "on which dates was code X logged" a lookup. Code can see each of these in the question."""
    plan = frame["plan"]
    if plan["operation"] == "not_answerable":
        return
    said = question.lower()
    literal = lambda code: bool(code) and bool(re.search(rf"(?<![a-z0-9]){re.escape(str(code).lower())}(?![a-z0-9])", said))
    npt_codes = {(e.npt_code or "").upper() for e in engine.events} - {""}
    # A runnable plan is a question over time, whatever kind the model gave it.
    if frame["kind"] in ("lookup_by_date", "lookup", "other"):
        frame["kind"] = "over_time"
    # The days are the question's, when it names any.
    if dates:
        plan["date_from"], plan["date_to"] = min(dates), max(dates)
    # A non-productive code stands if the question writes it, or if the reports use it and the question does not
    # speak of non-productive time in general ("waiting on equipment" may well mean WOE; "non-productive time" does
    # not mean KICK).
    code = str(plan["npt_code"] or "").upper()
    if code and not literal(code) and (code not in npt_codes or SAYS_NON_PRODUCTIVE.search(question)):
        plan["npt_code"] = ""
    if plan["non_productive"] and not plan["npt_code"] and not SAYS_NON_PRODUCTIVE.search(question):
        plan["non_productive"] = False
    # An activity code that is a field name is no code; and with non-productive time asked in general, an activity
    # code the question does not write narrows it wrongly.
    activity = str(plan["code"] or "")
    if activity.lower() in NOT_A_CODE or (plan["non_productive"] and activity and not literal(activity)
                                         and activity.lower() != "non_productive"):
        plan["code"] = ""


def frame_question(question: str, engine: Engine, client) -> tuple[dict, Any]:
    """The question's frame: kind, report type, query plan and problem. An answer that is not a frame gives the empty
    frame, which routes to the end-of-well lanes. What code reads in the question wins over what the model said."""
    call = client.chat([{"role": "system", "content": frame_system(engine)}, {"role": "user", "content": question}],
                       schema=FRAME_SCHEMA, max_tokens=320)
    parsed = call.parsed if isinstance(call.parsed, dict) else {}
    # A hosted endpoint may not enforce the schema, so the field types are checked here too.
    typed = all(_of_type(parsed.get(key, empty), empty) for key, empty in EMPTY_PLAN.items())
    problem = _problem(parsed)
    valid = (typed and problem is not None and parsed.get("kind") in KINDS and parsed.get("report_type") in REPORT_TYPES
             and parsed.get("operation") in PLAN_SCHEMA["properties"]["operation"]["enum"]
             and parsed.get("group_by", "") in PLAN_SCHEMA["properties"]["group_by"]["enum"])
    frame = {"kind": parsed["kind"], "report_type": parsed["report_type"],
             "plan": {key: parsed.get(key, empty) for key, empty in EMPTY_PLAN.items()}, "problem": problem} if valid \
        else {"kind": "other", "report_type": "unknown", "plan": dict(EMPTY_PLAN), "problem": dict(EMPTY_PROBLEM)}
    named = well_names(question)
    wells = named & engine.wells
    if len(wells) == 1:
        frame["plan"]["well"] = next(iter(wells))
    elif not wells and any(name[0].isalpha() and not NOT_A_WELL.fullmatch(name) for name in named):
        # The question names a well by letters and number (ZZ-9) and the engine holds no such well: a total must
        # not be computed on another well's events, whatever well the model wrote into the plan.
        frame["plan"]["operation"] = "not_answerable"
    elif len(wells) > 1:
        frame["kind"] = "across_wells"
    dates = question_dates(question)
    _check_plan(frame, question, dates, engine)
    if frame["kind"] == "cause":
        # The model's date, depth and keywords are kept only where the question says them too (B-F72): they are
        # asked for as the question's own words, and Qwen3-8B added a keyword of its own ("kick") to a question
        # that did not say it. Its non-productive code is kept: turning "wait on equipment" into WOE is its job.
        problem = frame["problem"]
        said = question.lower()

        def in_question(phrase: str) -> bool:
            words = reasoning._words(str(phrase))
            return bool(words) and all(re.search(rf"\b{re.escape(w)}", said) for w in words)

        if len(dates) == 1:
            problem["date"] = next(iter(dates))
        elif not dates and not _date_said(str(problem["date"]), said):
            problem["date"] = ""  # the question names no day, in any form: the model's day is its own
        problem["keywords"] = [k for k in problem["keywords"] if in_question(k)]
        if problem["depth_ft"]:
            depth = int(problem["depth_ft"])
            if not re.search(rf"(?<![\d.,])(?:{depth:,}|{depth})(?![\d]|[.,]\d)", question):
                problem["depth_ft"] = 0
    return frame, call


def route(frame: dict, mode: str = "allow_fallback") -> list[str]:
    """The lanes for a frame, in order. `exact` mode leaves out passages (D-59)."""
    if frame["kind"] == "cause":
        lanes = ["reasoning"]
    elif frame["kind"] == "over_time" and frame["plan"]["operation"] != "not_answerable":
        lanes = ["events"]
    elif frame["report_type"] == "daily":
        lanes = ["passages"]
    else:
        # End-of-well, both and unknown.
        lanes = ["well_facts", "passages"]
    return [lane for lane in lanes if mode != "exact" or lane != "passages"]


def _fallback(question: str, frame: dict, engine: Engine, routed: list[str]) -> Evidence | None:
    """Passages when no routed lane found anything: of the daily reports for a question over time, about causes
    or about the daily reports, else of the end-of-well reports."""
    daily_first = routed in (["events"], ["reasoning"]) or frame["report_type"] == "daily"
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
            "withheld_values": [], **score_answer(q, expected, "answered" if values else status, values),
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


def _reasoning_row(q: dict, evidence: Evidence, answer_client, gold: dict, mode: str) -> tuple[dict, int]:
    """A question about causes (specification §8.6). Several problems: the row lists them and asks which, with no
    answer call. One: one call for the two lists, checked in code. Returns the row and its number of answer calls."""
    pack = evidence.reasoning
    if pack["problem"] is None:
        result = {"problem": None, "candidates": pack["candidates"], "evidence": [], "evidence_chars": 0,
                  "stated": [], "possible": [], "possible_hidden": 0, "removed": {"stated": 0, "possible": 0},
                  "citations_named_shown": True, "missing": [], "valid": True}
        row = _row_without_a_call(q, gold, "ask_which", [], [], [], [])
        return {**row, "answer_text": reasoning.ask_text(pack["candidates"]), "reasoning": result}, 0
    result, call = reasoning.answer(q["question"], evidence, answer_client, mode)
    kept = result["stated"] + result["possible"]
    citations = list({(c["chunk"], c["how"]): {"chunk": c["chunk"], "how": c["how"]}
                      for item in kept for c in item["citations"]}.values())
    status = "answered" if kept else ("not_stated" if result["valid"] else "invalid")
    row = _row_without_a_call(q, gold, status, [], [], [], citations)
    row.update(citations_in_retrieved=result["citations_named_shown"], passages=len(result["evidence"]),
               prompt_tokens=call.prompt_tokens, completion_tokens=call.completion_tokens, seconds=(call.seconds or getattr(call, "cached_seconds", 0.0)),
               cached=call.cached)
    return {**row, "answer_text": reasoning.answer_text(result), "reasoning": result}, 1


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
    shown: dict[str, list] = {"shown_passages": [], "shown_facts": []}
    if computed:
        row = _computed_row(q, computed, gold)
        shown["shown_passages"] = computed["source_chunks"][:5]
    elif "reasoning" in by_lane:
        row, answer_calls = _reasoning_row(q, by_lane["reasoning"], answer_client, gold, mode)
        calls += answer_calls
        shown["shown_passages"] = by_lane["reasoning"].passages
    elif not found:
        # Nothing to answer from: in exact mode the graphs hold no answer, so no answer is generated.
        sources = _fallback(question, frame, engine, routed) if mode == "exact" else None
        row = {**_row_without_a_call(q, gold, "not_found_in_graph" if mode == "exact" else "not_stated", [], [], [], []),
               "sources": sources.passages if sources else []}
        shown["shown_passages"] = row["sources"]
    else:
        facts, passages = by_lane.get("well_facts"), by_lane.get("passages")
        hits = passages.passages if passages else facts.passages
        # A fact can cite a chunk the engine does not hold (facts built on an older package than the one loaded):
        # the fact still counts, its passage cannot be shown.
        hits = [cid for cid in hits if cid in engine.by_id()]
        answer_format = passages.answer_format if passages else facts.answer_format
        sheet = fact_sheet(facts.facts, limit=SHEET_LINES) if facts else {}
        graph = "\n".join(sheet[w] for w in sorted(well_names(question)) if w in sheet)
        row = answer_one(q, hits, graph, engine.by_id(), answer_client, gold, answer_format=answer_format,
                         max_tokens=MULTI_WELL_TOKENS if answer_format == "evidence_first" else 400)
        calls = 2
        shown = {"shown_passages": hits, "shown_facts": shown_facts(facts.facts) if facts else []}
    # The reports the evidence came from: a daily question can fall back to end-of-well passages, and must say so.
    answered_from = next((e.report_type for e in found if e.lane != "well_facts"), "end_of_well") if found else None
    # What was shown, for whoever displays the answer: passages by ID, and the facts of the sheet.
    out = {**row, **shown, "frame": frame, "lanes": [e.lane for e in found], "mode": mode, "fallback": fallback,
           "answered_from": answered_from,
           "computed": computed, "calls": calls, "frame_prompt_tokens": call.prompt_tokens,
           "frame_completion_tokens": call.completion_tokens, "frame_seconds": (call.seconds or getattr(call, "cached_seconds", 0.0))}
    if "stated_causes" in q:
        # A reasoning question with its gold (graphrag/README.md): scored by the probe's two measures.
        out["reasoning_score"] = reasoning.score(out, q)
        out["correct"] = out["reasoning_score"]["correct"]
    return out


# ---- pooled runs: every question set in one pool, with no lane given (E33) --------------------------------------

# The lane each set was answered by when the lane was chosen by hand (specification §8.4). It is what the
# coordinator's choice is judged against; it is not shown to the coordinator.
EXPECTED = {"prototype": "end_of_well", "probe": "end_of_well", "simulated": "end_of_well", "heldout": "end_of_well",
            "ak3_daily": "daily", "ak3_daily_heldout": "daily", "ak3_events": "events", "ak3_events_heldout": "events"}


def question_set(name: str) -> str:
    """A question set's name, or the path of a question file (a `.json` with `questions` and, if it has gold values,
    `facts`), given from the working folder or the repository. A file inside the repository is kept relative to it,
    so a run's record names it the same on every machine."""
    if name in QUESTION_SETS:
        return name
    path = Path(name)
    path = path if path.is_file() else ROOT / name
    if path.suffix != ".json" or not path.is_file():
        raise argparse.ArgumentTypeError(f"{name!r} is neither a question set ({', '.join(QUESTION_SETS)}) "
                                         f"nor a question file")
    path = path.resolve()
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)


def _question_file(name: str) -> tuple[Path, dict]:
    path = Path(name) if Path(name).is_absolute() else ROOT / name
    return path, json.loads(path.read_text(encoding="utf-8"))


def expected_lane(name: str) -> str:
    """A set's expected lane; a question file's is its `expected_lane`, by default `reasoning`."""
    return EXPECTED[name] if name in QUESTION_SETS else _question_file(name)[1].get("expected_lane", "reasoning")


def load_set(name: str) -> tuple[str, list[dict], dict[str, dict]]:
    """A set's short name, its questions and its gold. A question file's short name is its file name without
    `.json`; its facts are its gold, with `chunks` empty when a fact names none."""
    if name in QUESTION_SETS:
        return (name, *load_questions(name))
    path, data = _question_file(name)
    return path.stem, data["questions"], {f["id"]: dict(f, chunks=f.get("chunks", [])) for f in data.get("facts", [])}


def pooled(sets: list[str]) -> tuple[list[dict], dict[str, dict]]:
    """The questions and gold of several sets as one pool. IDs gain their set's name, since sets reuse them."""
    questions, gold = [], {}
    for name in sets:
        short, set_questions, set_gold = load_set(name)
        gold.update({f"{short}:{key}": fact for key, fact in set_gold.items()})
        questions += [dict(q, id=f"{short}:{q['id']}", gold=[f"{short}:{g}" for g in q["gold"]], set=short,
                           expected=expected_lane(name)) for q in set_questions]
    return questions, gold


def rightly_routed(row: dict) -> bool:
    """Whether the coordinator sent a question where its set was answered from by hand. A question about causes is
    routed by its kind; whether the reasoning lane then found the problem is scored apart (graphrag.reasoning)."""
    daily = row["frame"]["report_type"] == "daily"
    if row["expected"] == "reasoning":
        return row["frame"]["kind"] == "cause"
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
    needing = [name for name in sets if expected_lane(name) in ("daily", "events", "reasoning")]
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
    scored = any("reasoning_score" in r for r in rows)
    return {**summarize_pool(rows), **({"reasoning": reasoning.summarize(rows)} if scored else {}), "rows": rows}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("answer")
    a.add_argument("--questions", nargs="+", type=question_set, required=True,
                   help=f"question sets ({', '.join(QUESTION_SETS)}) or question files, such as a reasoning probe")
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
