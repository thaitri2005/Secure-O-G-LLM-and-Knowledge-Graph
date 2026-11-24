"""The question log (specification §4.6): every question asked, how it was answered, and any feedback on it.

Shown to domain experts, the application yields the real questions the project is waiting for (Q2, Q13), so the log
is a product of the build and not a debugging aid. It holds what users typed, so it stays inside the deployment:
the file version writes under ignored `data/interim/`.

`JsonlQuestionLog` is for one machine and one server process. `PostgresQuestionLog` is the log on the shared stores,
in the tables of platform/sql/002_questions.sql (backend design §3); anything with these three methods can stand in.

    python -m backend.questions init        # apply 002_questions.sql to BACKEND_DSN; safe to run again
    python -m backend.questions counts      # questions asked, answered and marked wrong, per kind
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

TABLES = Path(__file__).resolve().parents[1] / "platform/sql/002_questions.sql"
# The query the log exists for (backend design §3).
COUNTS = """
SELECT kind, count(*) AS asked, count(*) FILTER (WHERE status = 'answered') AS answered,
       count(f.*) FILTER (WHERE f.verdict = 'wrong') AS marked_wrong
FROM questions q LEFT JOIN question_feedback f USING (question_id)
GROUP BY kind ORDER BY asked DESC
"""


class QuestionLog(Protocol):
    def add_question(self, entry: dict) -> None: ...

    def add_feedback(self, question_id: str, verdict: str, comment: str) -> None: ...

    def has_question(self, question_id: str) -> bool: ...


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["init", "counts"])
    parser.add_argument("--dsn", default=os.environ.get("BACKEND_DSN"), help="PostgreSQL address (default: BACKEND_DSN)")
    args = parser.parse_args(argv)
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
