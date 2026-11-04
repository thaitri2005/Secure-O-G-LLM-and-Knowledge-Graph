"""A thin event graph from daily-report operations tables, for questions over time (E28, B-F45).

    python -m graphrag.events build --name E28_events
    python -m graphrag.events answer --name E28_graph --endpoint local-llama --model qwen3-8b

Well -> report date -> event -> activity code and non-productive code, each event keeping the chunks it came from.
Built with no model call from the tables in K1, and joined with the non-productive-time report by date and time.
There is no new ontology (B-D25). Answering: the model turns the question into a plan, code runs the plan on the
graph, and the model writes the answer from the result and the events' passages. Totals never depend on the model.

The graph is kept in memory as indexed records. It has no traversal beyond those links, so a win here is a win for
structured events, not for a graph database.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from .baseline import ANSWER_FORMATS, RESULTS, answer_questions, build, summarize
from .client import ModelClient, load_endpoints
from .data import appendix_chunks_path, load_chunks
from .ontology import table_rows
from .retrieval import page_dates, well_names
from .scoring import normalize

TIME = re.compile(r"\d{1,2}:\d\d")
WELL = "AK-3"
OPERATIONS = ("total_hours", "count_events", "count_days", "list_dates", "first_date", "last_date", "top_group",
              "depth_on_date", "first_date_depth_at_least", "depth_gain", "not_answerable")
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "operation": {"type": "string", "enum": list(OPERATIONS)},
        "well": {"type": "string"},
        "code": {"type": "string"},
        "non_productive": {"type": "boolean"},
        "npt_code": {"type": "string"},
        "date_from": {"type": "string"},
        "date_to": {"type": "string"},
        "group_by": {"type": "string", "enum": ["", "code", "date"]},
        "min_hours_per_day": {"type": "number"},
        "depth_ft": {"type": "number"},
    },
    "required": ["operation", "well", "code", "non_productive", "npt_code", "date_from", "date_to", "group_by",
                 "min_hours_per_day", "depth_ft"],
    "additionalProperties": False,
}
PLAN_SYSTEM = """You turn a question about a well's daily drilling reports into a query plan for an event database. Each event has a date, hours, an end measured depth, an activity code, and, when non-productive, a non-productive code.
Operations:
- total_hours: hours of the matching events.
- count_events: number of matching events.
- count_days: number of dates with matching events; with min_hours_per_day, only dates with at least that many matching hours.
- list_dates: the dates with matching events.
- first_date, last_date: the first or last date with matching events.
- top_group: which code or date (group_by) has the most hours among matching events.
- depth_on_date: the deepest end measured depth on date_from.
- first_date_depth_at_least: the first date with an end measured depth of at least depth_ft.
- depth_gain: the depth on date_to minus the depth on date_from.
- not_answerable: the question is not about these quantities.
Fill only what the question states. Use "" for an unused text field, false for non_productive unless the question is about non-productive time, and 0 for an unused number. Dates are YYYY-MM-DD. A question about one day has the same date_from and date_to. "well" is the well the question names, or "" if none. Write an activity code exactly as the question gives it, or choose it from this list when the question describes the activity in words:
"""
RESULT_NOTE = ("\nAn event database result may come before the passages. It was computed in code from the reports' operations "
               "tables, so it counts as stated: give its value as the answer and cite the first passage. If it says no events "
               "match, return status \"not_stated\".")


@dataclass
class Event:
    date: str
    start: str
    end: str
    hours: float
    end_md: int
    code: str
    description: str
    chunks: list[str] = field(default_factory=list)
    npt_code: str | None = None


def _number(text: str) -> float | None:
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _chunk_for(parts: list, row: int) -> list[str]:
    match = [c.id for c in parts if c.row_start is not None and c.row_start <= row <= c.row_end]
    return match[:1] or [parts[0].id]


def build_events(chunks: list, tables: list[dict]) -> tuple[list[Event], dict[str, int]]:
    """Events from operations tables, then joined with the non-productive report. The attachments repeat the same
    rows and each loses some ("1 record not printed", tables read as text), so rows are merged by date and time."""
    dates = page_dates(chunks)
    by_table: dict[str, list] = {}
    for c in chunks:
        if c.table_id:
            by_table.setdefault(c.table_id, []).append(c)
    events: dict[tuple[str, str, str], Event] = {}
    stats: Counter = Counter()
    npt_tables = []
    for table in sorted(tables, key=lambda t: t["table_id"]):
        parts, rows = by_table.get(table["table_id"]), table_rows(table)
        if not parts or len(rows) < 2:
            continue
        head = " ".join(rows[0])
        if "NPT Code" in head:
            npt_tables.append((table, parts, rows))
        elif "Elapsed" in head and "Code" in head:
            date = dates.get((parts[0].doc_id, parts[0].page))
            for r, row in enumerate(rows[1:], 1):
                if len(row) < 5 or not TIME.fullmatch(row[0]) or not TIME.fullmatch(row[1]):
                    continue
                hours, md = _number(row[2]), _number(row[3])
                if not date or hours is None or md is None:
                    stats["rows skipped"] += 1
                    continue
                key = (date, row[0], row[1])
                if key in events:
                    events[key].chunks.extend(c for c in _chunk_for(parts, r) if c not in events[key].chunks)
                else:
                    events[key] = Event(date, row[0], row[1], hours, int(md), row[4], row[5] if len(row) > 5 else "",
                                        _chunk_for(parts, r))
    stats["from operations tables"] = len(events)
    for table, parts, rows in npt_tables:
        for r, row in enumerate(rows[1:], 1):
            if len(row) < 8 or not TIME.fullmatch(row[3]) or not TIME.fullmatch(row[4]):
                continue
            hours, md = _number(row[5]), _number(row[6])
            if hours is None or md is None:
                stats["rows skipped"] += 1
                continue
            key = (normalize(row[2]), row[3], row[4])
            if key not in events:
                # The operations table lost this row; the report still gives its code and depth.
                events[key] = Event(key[0], key[1], key[2], hours, int(md), row[7], row[8] if len(row) > 8 else "", [])
                stats["added from the non-productive report"] += 1
            events[key].npt_code = row[0]
            events[key].chunks.extend(c for c in _chunk_for(parts, r) if c not in events[key].chunks)
            stats["non-productive events"] += 1
    return sorted(events.values(), key=lambda e: (e.date, TIME_KEY(e.start), e.end)), dict(stats)


def TIME_KEY(text: str) -> int:
    hours, minutes = text.split(":")
    return int(hours) * 60 + int(minutes)


def run_plan(plan: dict, events: list[Event], well: str = WELL) -> tuple[str, list[Event]]:
    """Runs a plan in code. Returns the result as text, and the events it rests on. No matching events gives an
    empty list: an unknown well, code or period is "not stated", not zero."""
    operation = plan["operation"]
    if operation == "not_answerable" or (plan.get("well") and plan["well"].upper() != well):
        return "", []
    start, end = plan.get("date_from") or "", plan.get("date_to") or ""
    code, npt_code = (plan.get("code") or "").upper(), (plan.get("npt_code") or "").upper()
    non_productive = bool(plan.get("non_productive") or npt_code)
    # Planners put "non_productive" or the non-productive code in the code field too (E28). An activity code is
    # dropped only then: alone, an unknown code still means no events, so it is not stated.
    if npt_code or (non_productive and code not in {e.code.upper() for e in events}):
        code = ""
    if operation in ("depth_on_date", "depth_gain", "first_date_depth_at_least"):
        code, npt_code, non_productive = "", "", False

    def in_scope(e: Event) -> bool:
        return ((not code or e.code.upper() == code) and (not non_productive or e.npt_code is not None)
                and (not npt_code or (e.npt_code or "").upper() == npt_code)
                and (not start or e.date >= start) and (not end or e.date <= end))

    def depth(date: str) -> tuple[int | None, list[Event]]:
        rows = [e for e in events if e.date == date]
        return (max(e.end_md for e in rows), rows) if rows else (None, [])

    if operation == "depth_on_date":
        value, rows = depth(start or end)
        return (f"deepest end measured depth on {start or end} = {value} ft", rows) if rows else ("", [])
    if operation == "depth_gain":
        (first, a), (second, b) = depth(start), depth(end)
        return (f"end measured depth rose by {second - first} ft from {start} ({first} ft) to {end} ({second} ft)",
                a + b) if a and b else ("", [])
    if operation == "first_date_depth_at_least":
        rows = [e for e in events if e.end_md >= (plan.get("depth_ft") or 0)]
        return (f"first date with an end measured depth of at least {plan.get('depth_ft'):g} ft = {rows[0].date}",
                rows[:1]) if rows else ("", [])
    rows = [e for e in events if in_scope(e)]
    if not rows:
        return "", []
    what = " ".join(filter(None, [f"code {code}" if code else "", f"non-productive code {npt_code}" if npt_code else "",
                                  "non-productive" if non_productive and not npt_code else "",
                                  f"from {start} to {end}" if start or end else ""])) or "all events"
    day_hours: Counter = Counter()
    for e in rows:
        day_hours[e.date] += e.hours
    if operation == "total_hours":
        return f"total hours for {what} = {sum(e.hours for e in rows):g} ({len(rows)} events on {len(day_hours)} dates)", rows
    if operation == "count_events":
        return f"number of events for {what} = {len(rows)}", rows
    if operation == "count_days":
        minimum = plan.get("min_hours_per_day") or 0
        days = [d for d, h in day_hours.items() if h >= minimum]
        suffix = f" with at least {minimum:g} hours" if minimum else ""
        return f"number of dates for {what}{suffix} = {len(days)}", [e for e in rows if e.date in days]
    if operation == "list_dates":
        return f"dates for {what} = {', '.join(sorted(day_hours))}", rows
    if operation == "first_date":
        return f"first date for {what} = {rows[0].date}", rows[:1]
    if operation == "last_date":
        return f"last date for {what} = {rows[-1].date}", rows[-1:]
    if operation == "top_group":
        group_by = plan.get("group_by") or "code"
        totals: Counter = Counter()
        for e in rows:
            totals[e.date if group_by == "date" else e.code] += e.hours
        best, hours = totals.most_common(1)[0]
        return f"the {group_by} with the most hours for {what} = {best} ({hours:g} hours)", \
            [e for e in rows if (e.date if group_by == "date" else e.code) == best]
    return "", []


def code_list(events: list[Event]) -> str:
    """Each activity code with an example description from the reports, so no glossary has to be written."""
    examples: dict[str, str] = {}
    for e in events:
        if e.description and len(e.description) > len(examples.get(e.code, "")) and len(e.description) < 90:
            examples[e.code] = e.description
    return "\n".join(f"- {code}: for example \"{examples.get(code, '')}\"" for code in sorted({e.code for e in events}))


def load_inputs() -> tuple[list, list[dict]]:
    """The daily-report attachments and the non-productive-time report (appx-23)."""
    path = appendix_chunks_path()
    rows = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    wanted = sorted({r["doc_id"] for r in rows if "dailyreport" in r["doc_id"] or "-appx-23-" in r["doc_id"]})
    tables = [json.loads(line) for line in (path.parent / "tables.jsonl").read_text(encoding="utf-8").splitlines()]
    return load_chunks(wanted, path), [t for t in tables if t["doc_id"] in wanted]


def answer(args) -> dict:
    chunks, tables = load_inputs()
    events, stats = build_events(chunks, tables)
    client = ModelClient(load_endpoints()[args.endpoint], args.model)
    fallback = build("dates:wells:bm25", chunks)
    system = PLAN_SYSTEM + code_list(events)
    plans = []

    def retrieve(question: str) -> tuple[list[str], str]:
        call = client.chat([{"role": "system", "content": system}, {"role": "user", "content": question}],
                           schema=PLAN_SCHEMA, max_tokens=200)
        plan = call.parsed or {"operation": "not_answerable"}
        result, rows = run_plan(plan, events)
        sources = list(dict.fromkeys(c for e in rows for c in e.chunks))
        plans.append({"question": question, "plan": plan, "result": result, "source_chunks": sources,
                      "plan_prompt_tokens": call.prompt_tokens, "plan_completion_tokens": call.completion_tokens,
                      "plan_seconds": call.seconds})
        if plan.get("operation") == "not_answerable":
            return [c for c, _ in fallback.search(question, args.k)], ""
        if not result:
            return [c for c, _ in fallback.search(question, args.k)], "Event database result: no events match."
        return sources[:args.k], f"Event database result: {result}."

    rows = answer_questions(retrieve, chunks, client, questions=args.questions, answer_format=args.answer_format,
                            max_tokens=args.max_tokens, system_note=RESULT_NOTE)
    for row, plan in zip(rows, plans):
        row["plan"], row["graph_result"] = plan["plan"], plan["result"]
        row["graph_source_chunks"] = plan["source_chunks"]
    result = summarize(rows, client)
    return {"pool": "ak3_daily+appx-23", "retriever": "event graph; fallback dates:wells:bm25", "k": args.k,
            "question_set": args.questions, "endpoint": args.endpoint, "model": args.model,
            "answer_format": args.answer_format, "events": len(events), "build": stats,
            "planner_tokens": {"prompt": sum(p["plan_prompt_tokens"] for p in plans),
                               "completion": sum(p["plan_completion_tokens"] for p in plans)}, **result}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    a = sub.add_parser("answer")
    a.add_argument("--endpoint", default="local-llama")
    a.add_argument("--model", default="qwen3-8b")
    a.add_argument("--questions", default="ak3_events")
    a.add_argument("--k", type=int, default=5)
    a.add_argument("--max-tokens", type=int, default=400)
    a.add_argument("--answer-format", choices=ANSWER_FORMATS, default="status_first")
    for p in (a, b):
        p.add_argument("--name", required=True)
    args = parser.parse_args(argv)
    if args.command == "build":
        events, stats = build_events(*load_inputs())
        out: dict[str, Any] = {"method": "operations tables and the non-productive report, no model call", "llm_calls": 0,
                               "wells": sorted(well_names(WELL)), "build": stats, "events": [asdict(e) for e in events]}
    else:
        out = answer(args)
    (RESULTS / f"{args.name}.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k not in ("rows", "events")}, indent=2))


if __name__ == "__main__":
    main()
