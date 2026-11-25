"""Value matching and answer scoring, with the rules of the prototype (prototype/kgproto/profile.py,
prototype/kgproto/evaluate_qa.py) so that results compare with E10, except that a whole number must match exactly
(`same_value`)."""
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
    """Dates and identifiers exactly, ignoring punctuation and case. A whole number exactly: 1160 ft is not 1165 ft,
    and the old 0.5% let it pass (two answers in every recorded run, B-F85). A number with decimals within 0.5%,
    since reports round them."""
    if isinstance(b, str):
        return re.sub(r"\W", "", str(a)).lower() == re.sub(r"\W", "", b).lower()
    x = number(a)
    if x is None:
        return False
    return x == float(b) if float(b).is_integer() else abs(x - b) <= max(0.01, 0.005 * abs(b))


def matches(value: Any, fact: dict) -> bool:
    return any(same_value(value, v) for v in [fact["value"], *fact.get("alternatives", [])])


def score_answer(question: dict, expected: list[dict], status: str, values: list[Any]) -> dict[str, bool]:
    """End-to-end correctness. With no expected fact, the system must say that nothing is stated: a reply that broke
    (`invalid`), was withheld, or asked something back is not a correct refusal. No recorded run had such a row
    (checked on 25 November 2026), so earlier scores stand."""
    answered = status == "answered" and bool(values)
    no_extra = all(any(matches(v, e) for e in expected) for v in values) if answered else True
    if expected:
        found = answered and all(any(matches(v, e) for v in values) for e in expected)
        correct = found and no_extra
    else:
        correct = not answered and status in ("not_stated", "not_found_in_graph")
    return {"correct": correct, "no_wrong_values": no_extra}
