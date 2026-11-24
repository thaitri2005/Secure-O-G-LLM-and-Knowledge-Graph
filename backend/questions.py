"""The question log (specification §4.6): every question asked, how it was answered, and any feedback on it.

Shown to domain experts, the application yields the real questions the project is waiting for (Q2, Q13), so the log
is a product of the build and not a debugging aid. It holds what users typed, so it stays inside the deployment:
the file version writes under ignored `data/interim/`.

`JsonlQuestionLog` is for one machine. The PostgreSQL tables that replace it on the shared stores are designed in
docs/tracks/C-storage/backend-design.md; anything with these three methods can stand in.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol


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

    def _append(self, record: dict) -> None:
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as file:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def add_question(self, entry: dict) -> None:
        self._append({"type": "question", **entry})

    def add_feedback(self, question_id: str, verdict: str, comment: str) -> None:
        self._append({"type": "feedback", "question_id": question_id, "verdict": verdict, "comment": comment,
                      "at": now()})

    def has_question(self, question_id: str) -> bool:
        if not self.path.is_file():
            return False
        with self.lock, self.path.open(encoding="utf-8") as file:
            return any(record.get("type") == "question" and record.get("id") == question_id
                       for record in map(json.loads, filter(str.strip, file)))
