"""Citations checked in code (B-C07): the model's chunk ID and quote are claims, not facts.

A citation is kept only when the cited chunk was among the retrieved passages and the quote appears in it.
Otherwise the citation is attached from the retrieved passages: first the one containing the quote, then the
first one containing the value. An answer no retrieved passage supports gets no citation.
"""
from __future__ import annotations

import re

from .data import cited_id
from .scoring import squash


def _plain(text: str) -> str:
    return re.sub(r"(?<=\d),(?=\d{3}\b)", "", squash(text)).lower()


def _contains(text: str, needle: str) -> bool:
    """Case-, space- and thousands-separator-insensitive, so "1955" is found in "1,955 ft"."""
    return bool(squash(needle)) and _plain(needle) in _plain(text)


def resolve(answer: dict, hits: list[str], texts: dict[str, str], doc_id: str) -> tuple[str | None, str]:
    """Return (chunk ID or None, how): "model", "by_quote", "by_value" or "unsupported"."""
    # A model without schema enforcement can return a number where text is asked: read every field as text.
    chunk, quote, value = (str(answer.get(key) or "") for key in ("chunk", "quote", "value"))
    cited = cited_id(chunk, hits, doc_id)
    if cited in hits and _contains(texts[cited], quote):
        return cited, "model"
    for how, needle in (("by_quote", quote), ("by_value", value)):
        found = next((cid for cid in hits if _contains(texts[cid], needle)), None)
        if found:
            return found, how
    return None, "unsupported"


# Units as reports write them after a value, and the one form shown for each.
_UNITS = [(r"feet|foot|ft\.?|'(?!')", "ft"), (r"inch(?:es)?|in\.|\"", "in"), (r"lb/ft|lbs?/ft|ppf", "lb/ft"), (r"ppg|lb/gal", "ppg"),
          (r"°\s?f|deg(?:rees)?\.? ?f\b", "°F"), (r"psi", "psi"), (r"gpm", "gpm"), (r"hours?|hrs?\.?", "hours"), (r"days?", "days"),
          (r"met(?:er|re)s?|m\b", "m")]


def unit_in_text(value: str, text: str) -> str | None:
    """The unit the passage writes straight after the value, in one form ("1,955 feet" gives "ft"); None when the
    value is not there or nothing known follows it. A bare "in" is a preposition, not inches."""
    plain = _plain(str(value))
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", plain):
        return None
    found = re.search(rf"(?<![\d.]){re.escape(plain)}(?:\.0+)?(?!\d)[ \u00a0-]?(\S{{0,12}})", _plain(text))
    if not found:
        return None
    after = found.group(1).lower()
    return next((unit for pattern, unit in _UNITS if re.match(rf"(?:{pattern})(?![a-z])", after)), None)


def same_unit(a: str, b: str) -> bool:
    form = lambda u: next((unit for pattern, unit in _UNITS if re.fullmatch(pattern, u.strip().lower())), u.strip().lower())
    return form(a) == form(b)
