"""Checks on extracted facts before any of them reaches an answer (B-F24; specification §6.2 stage 6).

A fact is kept only if
1. its value is written in its source chunk (numbers compared without thousands separators, `9145.0` as `9145`);
2. its well name resolves to exactly one well name (`68-32 26S 9W` is 68-32; a casing size or `Bows` is no well),
   and that well is named somewhere in the fact's own document;
3. it is not a zero, which daily-report forms print for empty fields;
4. it does not contradict another kept fact: per (well, property, qualifier, context) the value supported by
   the most chunks wins, and a tie between different values drops the key.

Every rejection is counted by reason, so a run reports what validation removed.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from .citations import _contains
from .retrieval import well_names
from .scoring import normalize


def _value_text(value) -> str:
    text = str(value)
    return re.sub(r"\.0+$", "", text) if re.fullmatch(r"-?\d+\.0+", text) else text


def written_in(value, text: str) -> bool:
    plain = _value_text(value)
    if _contains(text, plain):
        return True
    # Dates are extracted as YYYY-MM-DD but written as "18 August 2016" or "09-Mar-19".
    return any(normalize(m) == plain for m in re.findall(r"\d{1,2}[ -][A-Za-z]{3,9}[ -]\d{2,4}|[A-Za-z]{3,9} \d{1,2}, \d{4}", text))


def validate(facts: list[dict], texts: dict[str, str]) -> tuple[list[dict], dict[str, int]]:
    """`texts` maps chunk IDs (`<document>#<chunk>`) to chunk text, for the whole pool."""
    named: dict[str, set[str]] = defaultdict(set)
    for chunk_id, text in texts.items():
        named[chunk_id.split("#")[0]] |= well_names(text)
    rejected: Counter = Counter()
    candidates = []
    for fact in facts:
        wells = well_names(str(fact.get("well") or ""))
        if len(wells) != 1:
            rejected["no single well name"] += 1
            continue
        if not wells <= named[fact["chunk"].split("#")[0]]:
            rejected["well not named in its document"] += 1
            continue
        if re.fullmatch(r"-?0+(\.0+)?", str(fact["value"])):
            rejected["zero value"] += 1
            continue
        if not written_in(fact["value"], texts.get(fact["chunk"], "")):
            rejected["value not in its chunk"] += 1
            continue
        candidates.append(dict(fact, well=wells.pop(), value=_value_text(fact["value"])))
    groups: dict[tuple, Counter] = defaultdict(Counter)
    for fact in candidates:
        key = (fact["well"], fact["property"], fact["qualifier"], str(sorted((fact.get("context") or {}).items())))
        groups[key][fact["value"]] += 1
    kept, seen = [], set()
    for fact in candidates:
        key = (fact["well"], fact["property"], fact["qualifier"], str(sorted((fact.get("context") or {}).items())))
        ranked = groups[key].most_common()
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            rejected["contradicted, tie"] += 1
            continue
        if fact["value"] != ranked[0][0]:
            rejected["contradicted, outvoted"] += 1
            continue
        if (key, fact["value"]) in seen:
            continue  # the same fact from another chunk; one line is enough
        seen.add((key, fact["value"]))
        kept.append(fact)
    return kept, dict(rejected)
