"""Parse EDC verifier choices and apply the pre-registered answer normalization."""
from __future__ import annotations

import re


def parse_choices(prompt: str) -> tuple[dict[str, str], str | None]:
    """Read choice letters in prompt order, including the optional none choice."""
    letters = dict(re.findall(r"^([A-Z])\. '([^']+)': ", prompt, re.M))
    none = re.search(r"^([A-Z])\. None of the above\.$", prompt, re.M)
    return letters, none[1] if none else None


def classify(answer: str, letters: dict[str, str], none_letter: str | None) -> str:
    """Mirror EDC's first-character decision, with diagnostic none recognition."""
    if answer and answer[0] in letters: return "choice"
    if (answer and answer[0] == none_letter) or answer.strip().lower().startswith("none"):
        return "none_of_above"
    return "unparsed"


def normalize_choice(answer: str) -> str:
    """Strip only the exact punctuation and answer prefix registered in the evaluation contract."""
    def strips(value):
        return value.lstrip().lstrip("\"'`*([").lstrip()
    value = strips(answer)
    prefix = re.match(r"(?i)(?:the\s+)?(?:correct\s+)?answer(?:\s+is)?\s*[:.\-]?\s*", value)
    if prefix:
        value = strips(value[prefix.end():])
    return value if value else answer
