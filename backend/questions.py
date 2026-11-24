"""The question log (specification §4.6): every question asked, how it was answered, and any feedback on it.

Shown to domain experts, the application yields the real questions the project is waiting for (Q2, Q13), so the log
is a product of the build and not a debugging aid. It holds what users typed, so it stays inside the deployment:
the file version writes under ignored `data/interim/`.

`JsonlQuestionLog` is for one machine and one server process. The PostgreSQL tables that replace it on the shared stores are designed in
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
