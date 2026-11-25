"""The question log (specification §4.6): every question asked, how it was answered, and any feedback on it.

Shown to domain experts, the application yields the real questions the project is waiting for (Q2, Q13), so the log
is a product of the build and not a debugging aid. It holds what users typed, so it stays inside the deployment:
the file version writes under ignored `data/interim/`.

`JsonlQuestionLog` is for one machine and one server process. `PostgresQuestionLog` is the log on the shared stores,
in the tables of platform/sql/002_questions.sql (backend design §3); anything with the methods of `QuestionLog` can
stand in. Both read the log back the same way (D-65): questions newest first, filtered and paged, each with its
feedback, and counts. A question's verdict is its latest mark, since a user may change their mind.

    python -m backend.questions init        # apply 002_questions.sql to BACKEND_DSN; safe to run again
    python -m backend.questions counts      # questions asked, answered and marked wrong, per kind
"""
from __future__ import annotations

import argparse
import math
import json
import os
import sys
import threading
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

TABLES = Path(__file__).resolve().parents[1] / "platform/sql/002_questions.sql"
# The query the log exists for (backend design §3).
COUNTS = """
WITH latest AS (SELECT DISTINCT ON (question_id) question_id, verdict FROM question_feedback
                ORDER BY question_id, feedback_id DESC)
SELECT kind, count(*) AS asked, count(*) FILTER (WHERE status = 'answered') AS answered,
       count(*) FILTER (WHERE l.verdict = 'wrong') AS marked_wrong
FROM questions q LEFT JOIN latest l USING (question_id)
GROUP BY kind ORDER BY asked DESC
"""


@dataclass(frozen=True)
class Filters:
    """Which logged questions to read. Unset fields do not filter."""
    kind: str | None = None          # the frame's kind
    status: str | None = None
    mode: str | None = None
    verdict: str | None = None       # right, wrong, or none: not marked; by the latest mark
    date_from: str | None = None     # YYYY-MM-DD, the day asked in UTC, inclusive
    date_to: str | None = None
    text: str | None = None          # in the question, ignoring case
    ids: tuple[str, ...] = ()


class QuestionLog(Protocol):
    def add_question(self, entry: dict) -> None: ...

    def add_feedback(self, question_id: str, verdict: str, comment: str) -> None: ...

    def has_question(self, question_id: str) -> bool: ...

    def questions(self, filters: Filters, limit: int | None = None, offset: int = 0) -> tuple[int, list[dict]]:
        """How many questions match, and the page of them, newest first: stored entries with `feedback`, a list of
        `{verdict, comment, at}` oldest first. No limit: all of them."""
        ...

    def question(self, question_id: str) -> dict | None:
        """One stored entry with its `feedback`, or None."""
        ...

    def counts(self, filters: Filters) -> dict:
        """`{questions, by_kind, by_status, by_verdict}` of the matching questions."""
        ...


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def verdict_of(entry: dict) -> str | None:
    return entry["feedback"][-1]["verdict"] if entry.get("feedback") else None


def tally(rows) -> dict:
    """Counts from `(kind, status, verdict, n)` rows; a missing verdict counts as `none`."""
    by_kind, by_status, by_verdict = Counter(), Counter(), Counter({"right": 0, "wrong": 0, "none": 0})
    for kind, status, verdict, n in rows:
        by_kind[kind or "unknown"] += n
        by_status[status or "unknown"] += n
        by_verdict[verdict or "none"] += n
    return {"questions": sum(by_kind.values()), "by_kind": dict(by_kind.most_common()),
            "by_status": dict(by_status.most_common()), "by_verdict": dict(by_verdict)}


class JsonlQuestionLog:
    """One JSON object per line, appended. Questions have `type: question`, feedback `type: feedback`."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        # The IDs of the questions on disk, read once: feedback is checked against them on every mark.
        self.ids: set[str] = set()
        if path.is_file():
            with path.open(encoding="utf-8") as file:
                self.ids = {record["id"] for record in map(json.loads, filter(str.strip, file))
                            if record.get("type") == "question" and "id" in record}

    def _append(self, record: dict) -> None:
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as file:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def add_question(self, entry: dict) -> None:
        self._append({"type": "question", **entry})
        self.ids.add(entry["id"])

    def add_feedback(self, question_id: str, verdict: str, comment: str) -> None:
        self._append({"type": "feedback", "question_id": question_id, "verdict": verdict, "comment": comment,
                      "at": now()})

    def has_question(self, question_id: str) -> bool:
        return question_id in self.ids

    # ---- reading back: the file is read on each call; the team reads the log rarely and it stays small ----------

    def _entries(self) -> list[dict]:
        """Every question with its feedback, newest first; on the same second, the later line first."""
        if not self.path.is_file():
            return []
        with self.lock, self.path.open(encoding="utf-8") as file:
            records = [json.loads(line) for line in file if line.strip()]
        entries: dict[str, dict] = {}
        for record in records:
            if record.get("type") == "question" and "id" in record:
                entries[record["id"]] = {k: v for k, v in record.items() if k != "type"} | {"feedback": []}
            elif record.get("type") == "feedback" and record.get("question_id") in entries:
                entries[record["question_id"]]["feedback"].append(
                    {"verdict": record["verdict"], "comment": record.get("comment", ""), "at": record.get("at")})
        return sorted(reversed(list(entries.values())), key=lambda e: e.get("asked_at") or "", reverse=True)

    @staticmethod
    def _matches(entry: dict, filters: Filters) -> bool:
        day = (entry.get("asked_at") or "")[:10]
        return ((not filters.kind or (entry.get("frame") or {}).get("kind") == filters.kind)
                and (not filters.status or entry.get("status") == filters.status)
                and (not filters.mode or entry.get("mode") == filters.mode)
                and (not filters.verdict or (verdict_of(entry) or "none") == filters.verdict)
                and (not filters.date_from or day >= filters.date_from)
                and (not filters.date_to or day <= filters.date_to)
                and (not filters.text or filters.text.lower() in entry.get("question", "").lower())
                and (not filters.ids or entry["id"] in filters.ids))

    def questions(self, filters: Filters, limit: int | None = None, offset: int = 0) -> tuple[int, list[dict]]:
        found = [e for e in self._entries() if self._matches(e, filters)]
        return len(found), found[offset:None if limit is None else offset + limit]

    def question(self, question_id: str) -> dict | None:
        return next((e for e in self._entries() if e["id"] == question_id), None)

    def counts(self, filters: Filters) -> dict:
        return tally(((e.get("frame") or {}).get("kind"), e.get("status"), verdict_of(e), 1)
                     for e in self._entries() if self._matches(e, filters))


LANES = ("end_of_well", "daily", "events", "reasoning")  # graphrag.coordinator's expected lanes of a question file


def question_set(entries: list[dict], today: str, filters: Filters, expected_lane: str | None = None) -> dict:
    """Logged questions as a question file in graphrag/gold/'s format, which `python -m graphrag.coordinator answer
    --questions <file>` runs. Gold is empty for a person to write; each question keeps its log ID and the day it
    was asked, oldest first. `expected_lane` is written only when chosen, since a file has one for all its
    questions and the coordinator scores routing by it."""
    chosen = {k: (list(v) if isinstance(v, tuple) else v) for k, v in vars(filters).items() if v}
    return {"status": f"COLLECTED from the application's question log on {today}; gold answers not yet written; "
                     "not expert-reviewed unless stated",
           "version": "0.1",
           **({"expected_lane": expected_lane} if expected_lane else {}),
           "collected": {"on": today, "questions": len(entries), "filters": chosen},
           "known_limits": [
               "Questions as users typed them, including ones about data the reports do not hold.",
               "kind is the frame the application gave when the question was asked, not a person's judgement.",
               *([] if expected_lane else ["No expected_lane: the coordinator then takes the file as reasoning "
                                           "questions, so its routing score means nothing for this file."])],
           "questions": [{"id": e["id"], "kind": (e.get("frame") or {}).get("kind") or "unknown",
                          "question": e["question"], "gold": [], "asked_at": e.get("asked_at"),
                          # What the application answered, so a person marking or correcting it sees it in the sheet
                          # (`python -m graphrag.expert sheet`).
                          "system_answer": e.get("answer_text"),
                          "system_values": [str(a["value"]) for a in e.get("answers") or []],
                          "feedback": e.get("feedback", [])} for e in reversed(entries)],
           "facts": []}


# The latest mark of each question; questions are filtered on these columns.
LATEST = """
WITH latest AS (SELECT DISTINCT ON (question_id) question_id, verdict FROM question_feedback
                ORDER BY question_id, feedback_id DESC)
"""


def where(filters: Filters) -> tuple[str, list]:
    """The WHERE clause of `Filters` over `questions q LEFT JOIN latest l`, with its parameters."""
    parts, values = [], []
    for column, value in (("q.kind", filters.kind), ("q.status", filters.status), ("q.mode", filters.mode)):
        if value:
            parts.append(f"{column} = %s")
            values.append(value)
    if filters.verdict:
        parts.append("l.verdict IS NULL" if filters.verdict == "none" else "l.verdict = %s")
        values += [] if filters.verdict == "none" else [filters.verdict]
    if filters.date_from:
        parts.append("(q.asked_at AT TIME ZONE 'UTC')::date >= %s::date")
        values.append(filters.date_from)
    if filters.date_to:
        parts.append("(q.asked_at AT TIME ZONE 'UTC')::date <= %s::date")
        values.append(filters.date_to)
    if filters.text:
        parts.append("strpos(lower(q.question), lower(%s)) > 0")
        values.append(filters.text)
    if filters.ids:
        parts.append("q.question_id = ANY(%s)")
        values.append(list(filters.ids))
    return ("WHERE " + " AND ".join(parts)) if parts else "", values


def utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


class PostgresQuestionLog:
    """The log in PostgreSQL: one row in `questions` per question, with the whole entry in `record`, and one row in
    `question_feedback` per mark. It applies no SQL file itself (`python -m backend.questions init` does). A
    connection per call: questions come one at a time, and a restarted database needs no reconnect logic."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        # Fails at start, not at the first question, when the database does not answer or lacks the tables.
        with self._connect() as conn:
            conn.execute("SELECT 1 FROM questions, question_feedback LIMIT 0")

    def _connect(self):
        import psycopg
        return psycopg.connect(self.dsn)

    def add_question(self, entry: dict) -> None:
        from psycopg.types.json import Jsonb
        frame, cost = entry["frame"], entry["cost"]
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO questions (question_id, asked_at, question, mode, forced_lane, kind, report_type, lanes, "
                "fallback, answered_from, status, answer_text, calls, seconds, record) "
                "VALUES (%s, coalesce(%s::timestamptz, now()), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (entry["id"], entry.get("asked_at"), entry["question"], entry["mode"], entry.get("forced_lane"),
                 frame["kind"], frame["report_type"], list(entry["lanes"]), entry["fallback"], entry["answered_from"],
                 entry["status"], entry.get("answer_text"), cost["calls"], cost["seconds"], Jsonb(entry)))

    def add_feedback(self, question_id: str, verdict: str, comment: str) -> None:
        with self._connect() as conn:
            conn.execute("INSERT INTO question_feedback (question_id, verdict, comment) VALUES (%s, %s, %s)",
                         (question_id, verdict, comment))

    def has_question(self, question_id: str) -> bool:
        with self._connect() as conn:
            return conn.execute("SELECT 1 FROM questions WHERE question_id = %s", (question_id,)).fetchone() is not None

    # ---- reading back ------------------------------------------------------------------------------------------

    @staticmethod
    def _with_feedback(conn, rows: list[tuple]) -> list[dict]:
        """Stored entries from `(question_id, asked_at, record)` rows, with the columns' ID and time and their feedback."""
        marks: dict[str, list[dict]] = {}
        for question_id, verdict, comment, at in conn.execute(
                "SELECT question_id, verdict, comment, at FROM question_feedback WHERE question_id = ANY(%s) "
                "ORDER BY feedback_id", ([r[0] for r in rows],)).fetchall():
            marks.setdefault(question_id, []).append({"verdict": verdict, "comment": comment, "at": utc(at)})
        return [dict(record, id=question_id, asked_at=utc(asked_at), feedback=marks.get(question_id, []))
                for question_id, asked_at, record in rows]

    def questions(self, filters: Filters, limit: int | None = None, offset: int = 0) -> tuple[int, list[dict]]:
        clause, values = where(filters)
        joined = f"{LATEST} SELECT {{}} FROM questions q LEFT JOIN latest l USING (question_id) {clause}"
        with self._connect() as conn:
            total = conn.execute(joined.format("count(*)"), values).fetchone()[0]
            rows = conn.execute(joined.format("q.question_id, q.asked_at, q.record")
                                + " ORDER BY q.asked_at DESC, q.question_id DESC LIMIT %s OFFSET %s",
                                [*values, limit, offset]).fetchall()
            return total, self._with_feedback(conn, rows)

    def question(self, question_id: str) -> dict | None:
        with self._connect() as conn:
            rows = conn.execute("SELECT question_id, asked_at, record FROM questions WHERE question_id = %s",
                                (question_id,)).fetchall()
            return self._with_feedback(conn, rows)[0] if rows else None

    def counts(self, filters: Filters) -> dict:
        clause, values = where(filters)
        with self._connect() as conn:
            return tally(conn.execute(f"{LATEST} SELECT q.kind, q.status, l.verdict, count(*) FROM questions q "
                                      f"LEFT JOIN latest l USING (question_id) {clause} GROUP BY 1, 2, 3",
                                      values).fetchall())


def percentile(values: list[float], share: float) -> float | None:
    """The value below which `share` of `values` lie (nearest rank); None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(share * len(ordered)) - 1))]


def statistics(entries: list[dict]) -> dict:
    """What the log says about how the application is doing (specification §11.2): how many questions, how they
    ended, which lanes answered, and what a question costs. Timings leave out failed questions and those a model
    call answered from the request cache, whose seconds are 0."""
    timed = [e for e in entries if e.get("status") != "error" and not e.get("cached_calls")]
    seconds = [float((e.get("cost") or {}).get("seconds") or 0) for e in timed]
    waits = [float(e.get("queue_seconds") or 0) for e in entries if "queue_seconds" in e]
    total = len(entries)

    def mean(key: str) -> float | None:
        return round(sum((e.get("cost") or {}).get(key) or 0 for e in timed) / len(timed), 1) if timed else None

    def share(count: int) -> float:
        return round(count / total, 3) if total else 0.0

    statuses = Counter(e.get("status") or "unknown" for e in entries)
    not_found = statuses["not_found_in_graph"] + statuses["not_stated"]
    return {"questions": total, "by_status": dict(statuses.most_common()),
            "by_lane": dict(Counter("+".join(e.get("lanes") or []) or "none" for e in entries).most_common()),
            "by_error": dict(Counter(e["error"] for e in entries if e.get("error")).most_common()),
            "error_rate": share(statuses["error"]), "not_found_rate": share(not_found),
            "fallback_rate": share(sum(bool(e.get("fallback")) for e in entries)),
            "marked_wrong": sum(verdict_of(e) == "wrong" for e in entries),
            "timed_questions": len(timed), "seconds_p50": percentile(seconds, 0.5), "seconds_p95": percentile(seconds, 0.95),
            "queue_seconds_p95": percentile(waits, 0.95), "calls_mean": mean("calls"),
            "prompt_tokens_mean": mean("prompt_tokens"), "completion_tokens_mean": mean("completion_tokens")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["init", "counts", "stats"])
    parser.add_argument("--dsn", default=os.environ.get("BACKEND_DSN"), help="PostgreSQL address (default: BACKEND_DSN)")
    parser.add_argument("--file", type=Path, help="stats only: a question log file (JSON lines) instead of PostgreSQL")
    parser.add_argument("--since", help="stats only: questions asked on or after this day (YYYY-MM-DD)")
    args = parser.parse_args(argv)
    if args.command == "stats":
        if not args.file and not args.dsn:
            parser.error("set BACKEND_DSN, or pass --dsn or --file")
        source = JsonlQuestionLog(args.file) if args.file else PostgresQuestionLog(args.dsn)
        print(json.dumps(statistics(source.questions(Filters(date_from=args.since))[1]), indent=2))
        return 0
    if not args.dsn:
        parser.error("set BACKEND_DSN or pass --dsn")
    import psycopg
    with psycopg.connect(args.dsn) as conn:
        if args.command == "init":
            conn.execute(TABLES.read_text(encoding="utf-8"))
            print(f"applied {TABLES.name}")
        else:
            for kind, asked, answered, wrong in conn.execute(COUNTS).fetchall():
                print(f"{kind}: {asked} asked, {answered} answered, {wrong} marked wrong")
    return 0


if __name__ == "__main__":
    sys.exit(main())
