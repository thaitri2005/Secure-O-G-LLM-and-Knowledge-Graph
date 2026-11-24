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


def units_in_text(value: str, text: str) -> list[str]:
    """Every unit the passage writes straight after the value, each in one form ("1,955 feet" gives "ft"), in the
    order met. A compound unit ("40 ft/hr", "5,000 ft-lbs") is not one of the simple units and gives nothing, and a
    bare "in" is a preposition, not inches."""
    plain = _plain(str(value))
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", plain):
        return []
    out = []
    for found in re.finditer(rf"(?<![\d.]){re.escape(plain)}(?:\.0+)?(?!\d)[ \u00a0-]?(\S{{0,12}})", _plain(text)):
        after = found.group(1).lower()
        unit = next((unit for pattern, unit in _UNITS if re.match(rf"(?:{pattern})(?![a-z0-9/²³-])", after)), None)
        if unit and unit not in out:
            out.append(unit)
    return out


def unit_in_text(value: str, text: str) -> str | None:
    """The first of `units_in_text`, or None."""
    return next(iter(units_in_text(value, text)), None)


def simple_unit(unit: str) -> str | None:
    """The one form of a unit the model gave, when it is one of the simple units ("feet" gives "ft"); None for
    anything else ("ft/hr", "ft MD", ""), which is left as the model gave it."""
    return next((form for pattern, form in _UNITS if re.fullmatch(pattern, unit.strip().lower())), None)


def checked_unit(value: str, unit: str, text: str) -> str:
    """The unit to show for an answer, checked against the cited passage. It changes only a simple unit that the
    passage contradicts: the passage writes the value with units, and the model's is none of them ("in" for a depth
    written "1,955 in contrast to ... to 1,955'"). A unit the passage gives nowhere, with "in" straight after the
    value as a preposition, is dropped. Anything else stays as the model gave it."""
    given = simple_unit(unit) or ("in" if unit.strip().lower() == "in" else None)  # a model writes inches as "in"
    if given is None:
        return unit
    written = units_in_text(value, text)
    if written:
        return unit if given in written else written[0]
    return "" if given == "in" and preposition_after(value, text) else unit


def same_unit(a: str, b: str) -> bool:
    form = lambda u: simple_unit(u) or u.strip().lower()
    return form(a) == form(b)


def preposition_after(value: str, text: str) -> bool:
    """Whether the passage writes the value and then the word "in" as a preposition ("1,955 in contrast to")."""
    plain = _plain(str(value))
    return bool(re.fullmatch(r"-?\d+(?:\.\d+)?", plain)) and \
        bool(re.search(rf"(?<![\d.]){re.escape(plain)}(?!\d) in [a-z]", _plain(text)))
