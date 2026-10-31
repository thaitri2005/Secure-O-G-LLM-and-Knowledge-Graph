"""Value matching and answer scoring, with the same rules as the prototype (prototype/kgproto/profile.py,
prototype/kgproto/evaluate_qa.py) so that results compare with E10."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

DATE_FORMATS = ["%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%d-%b-%Y", "%d-%B-%Y",
                "%d/%m/%Y", "%d.%m.%Y", "%Y/%m/%d", "%d-%b-%y"]  # 09-Mar-19 in daily reports


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize(value: str) -> str:
    """Dates to YYYY-MM-DD and numbers without thousands separators, in code rather than by the model (B-D10)."""
    text = squash(str(value)).rstrip(".")
    cleaned = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)


def number(value: Any) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return round(float(match.group()), 6) if match else None


def same_value(a: Any, b: Any) -> bool:
    """Numbers within 0.5%; dates and identifiers exactly, ignoring punctuation and case."""
    if isinstance(b, str):
        return re.sub(r"\W", "", str(a)).lower() == re.sub(r"\W", "", b).lower()
    x = number(a)
    return x is not None and abs(x - b) <= max(0.01, 0.005 * abs(b))


def matches(value: Any, fact: dict) -> bool:
    return any(same_value(value, v) for v in [fact["value"], *fact.get("alternatives", [])])


def score_answer(question: dict, expected: list[dict], status: str, values: list[Any]) -> dict[str, bool]:
    """End-to-end correctness. With no expected fact, the system must not answer."""
    answered = status == "answered" and bool(values)
    no_extra = all(any(matches(v, e) for e in expected) for v in values) if answered else True
    if expected:
        found = answered and all(any(matches(v, e) for v in values) for e in expected)
        correct = found and no_extra
    else:
        correct = not answered
    return {"correct": correct, "no_wrong_values": no_extra}
