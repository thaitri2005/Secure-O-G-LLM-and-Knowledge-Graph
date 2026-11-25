"""From a person's answers to a question set the engine can run, with no model call.

A person who knows the reports gives answers in one of two ways, and both end as a question file in
`graphrag/gold/`'s format:

    1. In the application: mark an answer right or wrong and leave a comment. The team downloads the questions
       (Questions page, "Download these as a question set") and turns the file into a sheet.
    2. In a spreadsheet: one row per question, the expected answer typed in plain words.

    python -m graphrag.expert sheet collected_2026-12-01.json --out pilot.csv      # a sheet to fill in Excel
    python -m graphrag.expert sheet --blank --out pilot.csv                        # an empty sheet with examples
    python -m graphrag.expert build pilot.csv --name pilot_v1 --written-by "..."   # graphrag/gold/pilot_v1.json
    python -m graphrag.expert check graphrag/gold/pilot_v1.json                    # is the file runnable?
    python -m graphrag.coordinator answer --questions graphrag/gold/pilot_v1.json --k1 --name pilot_v1

A question file may also be written by hand with the same plain fields: `answer` and `expected_lane` on a question
(see `expand`). The guide for the people involved is docs/EXPERT_PILOT.md.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from .scoring import normalize, squash

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "graphrag/gold"
LANES = ("end_of_well", "daily", "events", "reasoning")
COLUMNS = ["id", "question", "system_answer", "mark", "comment", "expected_answer", "lane", "problem_date",
           "key_words", "source"]
NOT_STATED = {"not stated", "not in the reports", "not in the report", "none", "n/a", "khong co", "không có"}
ASK_WHICH = {"ask which", "ask back", "which one", "hỏi lại"}
ISO = re.compile(r"\d{4}-\d{2}-\d{2}$")
PLAIN_NUMBER = re.compile(r"-?\d+(?:\.\d+)?$")
NUMBER_WITH_UNIT = re.compile(r"(-?\d+(?:\.\d+)?)\s*[A-Za-z%°/\"'³²]{1,8}$")
EXAMPLES = [
    {"id": "example-1", "question": "What was the total depth of AK-3?", "expected_answer": "1955 ft",
     "lane": "end_of_well", "source": "End-of-well report, page 4"},
    {"id": "example-2", "question": "Who supervised the drilling of AK-3?",
     "expected_answer": "Monty Keown | M. Keown", "lane": "end_of_well"},
    {"id": "example-3", "question": "How many hours did AK-3 wait on weather in August 2016?",
     "expected_answer": "24", "lane": "events"},
    {"id": "example-4", "question": "What was the mud weight on AK-3 on 1 January 2030?",
     "expected_answer": "not stated", "lane": "daily"},
    {"id": "example-5", "question": "Why did AK-3 lose the whole day of 13 August 2016?",
     "expected_answer": "a weather delay", "lane": "reasoning", "problem_date": "2016-08-13",
     "key_words": "weather"},
]


def parts(text: Any, separator: str) -> list[str]:
    return [p for p in (squash(str(x)) for x in str(text or "").split(separator)) if p]


def gold_value(text: str) -> Any:
    """A typed answer as the scorer compares it: a number (matched within 0.5%), a date as YYYY-MM-DD, or words
    (matched exactly, ignoring case and punctuation). "1,955 ft" is the number 1955: the unit is not scored."""
    value = normalize(text)
    if ISO.match(value):
        return value
    if PLAIN_NUMBER.match(value):
        return float(value)
    with_unit = NUMBER_WITH_UNIT.match(value)
    return float(with_unit.group(1)) if with_unit else value


def facts_of(question_id: str, answer: Any, source: str = "") -> list[dict]:
    """One gold fact per expected value. Values are separated by `;`, other accepted wordings of one value by `|`."""
    values = answer if isinstance(answer, list) else parts(answer, ";")
    facts = []
    for n, value in enumerate(values, 1):
        first, *others = [gold_value(v) for v in parts(value, "|")] or [""]
        facts.append({"id": f"{question_id}.a{n}", "value": first, "chunks": [],
                      **({"alternatives": others} if others else {}), **({"source_note": source} if source else {})})
    return facts


def expand(data: dict) -> dict:
    """A question file with the plain fields turned into gold, so that a person can write

        {"id": "p01", "question": "...", "answer": "1955 ft", "expected_lane": "end_of_well"}

    instead of a fact list. `answer` is one value, several separated by `;`, a list, or "not stated". On a cause
    question (`expected_lane` reasoning, or kind `cause`) it is the cause the reports state, with `key_words` and
    `problem_date` beside it; "ask which" and "not stated" are the two other outcomes. A question that already
    has `gold` or `stated_causes` is left as it is."""
    questions, facts = [], list(data.get("facts", []))
    for q in data["questions"]:
        q = dict(q)
        answer = q.pop("answer", None)
        q.setdefault("gold", [])
        if answer is None or q["gold"] or "stated_causes" in q:
            questions.append(q)
            continue
        plain = squash(str(answer)).lower() if not isinstance(answer, list) else ""
        if q.get("expected_lane", data.get("expected_lane")) == "reasoning" or q.get("kind") == "cause":
            words = [parts(w, "|") for w in parts(q.pop("key_words", ""), ";")]
            causes = [] if plain in NOT_STATED | ASK_WHICH else (answer if isinstance(answer, list) else parts(answer, ";"))
            q.update(kind="cause", outcome="ask_which" if plain in ASK_WHICH else "fallback" if plain in NOT_STATED
                     else "answer",
                     stated_causes=[{"cause": c, "terms": words[n] if n < len(words) else [c], "chunks": []}
                                    for n, c in enumerate(causes)])
            if q.get("problem_date"):
                q["gold_problem"] = {"date": normalize(q.pop("problem_date"))}
        elif plain not in NOT_STATED:
            new = facts_of(q["id"], answer, q.pop("source", ""))
            facts += new
            q["gold"] = [f["id"] for f in new]
        questions.append(q)
    return {**data, "questions": questions, "facts": facts}


def problems(data: dict) -> list[str]:
    """What would make a run of this file fail or score wrongly. Empty when the file is ready."""
    found, seen = [], set()
    data = expand(data)
    facts = {f.get("id") for f in data.get("facts", [])}
    if data.get("expected_lane") not in (None, *LANES):
        found.append(f"expected_lane {data['expected_lane']!r} is not one of {', '.join(LANES)}")
    for n, q in enumerate(data.get("questions", []), 1):
        name = q.get("id") or f"question {n}"
        if not q.get("id") or q["id"] in seen:
            found.append(f"{name}: the ID is missing or used twice")
        seen.add(q.get("id"))
        if not squash(str(q.get("question", ""))):
            found.append(f"{name}: no question text")
        lane = q.get("expected_lane", data.get("expected_lane"))
        if lane not in LANES:
            found.append(f"{name}: no expected lane ({', '.join(LANES)}); its routing score would mean nothing")
        found += [f"{name}: gold {g!r} is not in facts" for g in q.get("gold", []) if g not in facts]
        for cause in q.get("stated_causes", []):
            if cause.get("terms") == [cause.get("cause")]:
                found.append(f"{name}: no key words for the cause {cause['cause']!r}; the answer would have to "
                             "repeat it word for word")
    return found


def summary(data: dict) -> dict:
    data = expand(data)
    lanes = [q.get("expected_lane", data.get("expected_lane")) or "none" for q in data["questions"]]
    return {"questions": len(lanes), "by_lane": {lane: lanes.count(lane) for lane in dict.fromkeys(lanes)},
            "with_an_expected_answer": sum(bool(q["gold"] or q.get("stated_causes")) for q in data["questions"]),
            "expected_not_stated_or_ask": sum(not q["gold"] and not q.get("stated_causes") for q in data["questions"])}


# ---- the sheet ----------------------------------------------------------------------------------------------------

def rows_of(data: dict) -> list[dict]:
    """A question file as sheet rows. A collected file (the application's export) brings what the application
    answered and the latest mark; where that mark is "right", the answer given is proposed as the expected one,
    for the person to keep or correct."""
    rows = []
    for q in data["questions"]:
        marks = q.get("feedback") or []
        mark = marks[-1]["verdict"] if marks else ""
        proposed = "; ".join(q.get("system_values") or []) if mark == "right" else ""
        rows.append({"id": q["id"], "question": q["question"], "system_answer": q.get("system_answer") or "",
                     "mark": mark, "comment": " / ".join(m["comment"] for m in marks if m.get("comment")),
                     "expected_answer": q.get("answer", proposed),
                     "lane": q.get("expected_lane", data.get("expected_lane", "")) or "",
                     "problem_date": q.get("problem_date", ""), "key_words": q.get("key_words", ""),
                     "source": q.get("source", "")})
    return rows


def write_sheet(rows: list[dict], path: Path) -> None:
    # utf-8-sig: Excel then reads Vietnamese text and the degree sign correctly.
    with path.open("w", encoding="utf-8-sig", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows({c: row.get(c, "") for c in COLUMNS} for row in rows)


def read_sheet(path: Path) -> list[dict]:
    """Rows of a filled sheet. Excel may save with `;` between cells; both are read."""
    text = path.read_text(encoding="utf-8-sig")
    first = text.splitlines()[0] if text.strip() else ""
    rows = list(csv.DictReader(text.splitlines(keepends=True), delimiter=";" if first.count(";") > first.count(",") else ","))
    missing = {"question", "expected_answer"} - set(rows[0] if rows else [])
    if missing:
        raise SystemExit(f"{path}: the sheet has no column {', '.join(sorted(missing))}. Start from "
                         "`python -m graphrag.expert sheet --blank`.")
    return [{k: squash(v or "") for k, v in row.items() if k} for row in rows]


def build(rows: list[dict], name: str, written_by: str, expert: bool, today: str,
          default_lane: str | None = None) -> tuple[dict, list[str]]:
    """A question file from sheet rows. Rows without an expected answer and the sheet's example rows are left out
    and named, since a question with no answer would be scored as "must say not stated"."""
    kept, left_out = [], []
    for n, row in enumerate(rows, 1):
        if not row.get("question") or row.get("id", "").startswith("example-"):
            continue
        if not row.get("expected_answer"):
            left_out.append(row.get("id") or f"row {n}")
            continue
        lane = (row.get("lane") or default_lane or "").lower().replace("-", "_").replace(" ", "_")
        kept.append({"id": row.get("id") or f"q{n:02d}", "question": row["question"],
                     "answer": row["expected_answer"], **({"expected_lane": lane} if lane else {}),
                     **{k: row[k] for k in ("problem_date", "key_words", "source", "comment") if row.get(k)}})
    who = (f"EXPERT: written or checked by {written_by}, a drilling expert" if expert else
           f"WRITTEN BY THE TEAM ({written_by}): not reviewed by a drilling expert, so not an evaluation (B-D22)")
    data = {"status": f"{who}. Built from a sheet on {today} by graphrag.expert. Frozen once a run is recorded on "
                      "it: a change goes into a new version.",
            "version": "0.1", "name": name, "written_by": written_by, "expert_reviewed": expert,
            "known_limits": ["Units are not scored: \"1955 ft\" and \"1955 m\" both match 1955.",
                             "Gold facts name no chunk, so retrieval is not scored on this file, only answers."],
            "questions": kept}
    return expand(data), left_out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    s = commands.add_parser("sheet", help="a question file, or nothing, as a sheet to fill in")
    s.add_argument("file", nargs="?", type=Path)
    s.add_argument("--blank", action="store_true", help="an empty sheet with five example rows")
    s.add_argument("--out", type=Path, required=True)
    b = commands.add_parser("build", help="a filled sheet as a question file in graphrag/gold/")
    b.add_argument("sheet", type=Path)
    b.add_argument("--name", required=True, help="the file's name without .json, with its version: pilot_v1")
    b.add_argument("--written-by", required=True, help="who wrote the expected answers")
    b.add_argument("--expert", action="store_true", help="that person is a drilling expert")
    b.add_argument("--lane", choices=LANES, help="the lane of rows that name none")
    b.add_argument("--out-dir", type=Path, default=GOLD)
    c = commands.add_parser("check", help="whether a question file is ready to run")
    c.add_argument("file", type=Path)
    args = parser.parse_args()

    if args.command == "sheet":
        if bool(args.file) == args.blank:
            raise SystemExit("Give a question file, or --blank.")
        rows = EXAMPLES if args.blank else rows_of(json.loads(args.file.read_text(encoding="utf-8")))
        write_sheet(rows, args.out)
        print(f"{args.out}: {len(rows)} rows. Fill expected_answer (and lane), then: python -m graphrag.expert build")
    elif args.command == "build":
        target = args.out_dir / f"{args.name}.json"
        if target.exists():
            raise SystemExit(f"{target} exists. Question sets are frozen: give the next version's name.")
        data, left_out = build(read_sheet(args.sheet), args.name, args.written_by, args.expert,
                               date.today().isoformat(), args.lane)
        if not data["questions"]:
            raise SystemExit("No row has an expected answer: nothing was written.")
        target.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{target}: {json.dumps(summary(data))}")
        if left_out:
            print(f"Left out, no expected answer: {', '.join(left_out)}")
        for line in problems(data):
            print(f"  to fix: {line}")
        print(f"Run it: python -m graphrag.coordinator answer --questions {target} --k1 --name {args.name}")
    else:
        data = json.loads(args.file.read_text(encoding="utf-8"))
        print(json.dumps(summary(data)))
        found = problems(data)
        for line in found:
            print(f"  to fix: {line}")
        raise SystemExit(1 if found else 0)


if __name__ == "__main__":
    main()
