"""Checks on extracted facts before any of them reaches an answer (B-F24; specification §6.2 stage 6).

A fact is kept only if
1. its value is written in its source chunk (numbers compared without thousands separators, `9145.0` as `9145`);
2. its well name resolves to exactly one well name (`68-32 26S 9W` is 68-32; a casing size or `Bows` is no well),
   and that well is named somewhere in the fact's own document;
3. it is not a zero, which daily-report forms print for empty fields;
4. it does not contradict another kept fact: per (well, property, qualifier, context) the value supported by
   the most chunks wins, and a tie between different values drops the key.

With `strict` (B-F32), a casing size in the context must also look like a casing size, be written in the fact's
chunk, and differ from the value. The value check alone passes facts with the wrong meaning: `10031`, the rig
number, as a casing size. A depth context must be written in the chunk too.

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


# Casing and hole sizes: 2-3/8 to 36 in., whole, with a fraction in eighths or sixteenths, or the same as a decimal.
CASING_SIZE = re.compile(r"(\d{1,2})(?:[- ](\d{1,2})/(\d{1,2})|\.(\d{1,3}))?\s*(?:\"|in\.?)?")
SIZE_DECIMALS = {"0", "00", "000", "5", "50", "500", "25", "250", "75", "750", "125", "375", "625", "875"}


def casing_size(text: str) -> float | None:
    """The size in inches when `text` looks like a casing or hole size, else None."""
    match = CASING_SIZE.fullmatch(text.strip())
    if not match:
        return None
    whole, top, bottom, decimals = match.groups()
    if decimals is not None and decimals not in SIZE_DECIMALS:
        return None
    if top and (int(bottom) not in (2, 4, 8, 16) or int(top) >= int(bottom)):
        return None
    size = int(whole) + (int(top) / int(bottom) if top else 0) + (float(f"0.{decimals}") if decimals else 0)
    return size if 2.375 <= size <= 36 else None


def context_problem(fact: dict, text: str) -> str | None:
    """Why a fact's context cannot be trusted, or None."""
    for key, value in (fact.get("context") or {}).items():
        if key == "casing_size_in":
            size = casing_size(str(value))
            if size is None:
                return "context is not a casing size"
            if re.fullmatch(r"\d+(\.\d+)?", str(fact["value"])) and float(fact["value"]) == size:
                return "value repeats its casing size"
            if not written_in(str(value).strip().rstrip('"').removesuffix("in.").strip(), text):
                return "context not in its chunk"
        elif key == "depth_ft" and not written_in(value, text):
            return "context not in its chunk"
    return None


def written_in(value, text: str) -> bool:
    plain = _value_text(value)
    if _contains(text, plain):
        return True
    # Dates are extracted as YYYY-MM-DD but written as "18 August 2016" or "09-Mar-19".
    return any(normalize(m) == plain for m in re.findall(r"\d{1,2}[ -][A-Za-z]{3,9}[ -]\d{2,4}|[A-Za-z]{3,9} \d{1,2}, \d{4}", text))


def validate(facts: list[dict], texts: dict[str, str], strict: bool = False) -> tuple[list[dict], dict[str, int]]:
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
        problem = context_problem(fact, texts.get(fact["chunk"], "")) if strict else None
        if problem:
            rejected[problem] += 1
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
