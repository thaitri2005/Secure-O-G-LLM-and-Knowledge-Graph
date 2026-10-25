"""Prototype well ontology v0.1, the extraction output schema, and deterministic claim validation."""
from __future__ import annotations

import re
from typing import Any

PROPERTIES = {
    "total_depth": {"unit": "ft", "qualifiers": ["actual", "planned"], "context": None,
                    "description": "final drilled depth of a well (actual) or the depth it was planned to reach (planned)"},
    "drilling_days": {"unit": "days", "qualifiers": ["actual", "planned"], "context": None,
                      "description": "total days of the drilling project including rig-up and rig-down"},
    "spud_to_release_days": {"unit": "days", "qualifiers": ["actual"], "context": None,
                             "description": "days from spud to rig release"},
    "spud_date": {"unit": "date", "qualifiers": ["actual"], "context": None, "description": "date drilling started (YYYY-MM-DD)"},
    "rig_release_date": {"unit": "date", "qualifiers": ["actual"], "context": None, "description": "date the rig was released (YYYY-MM-DD)"},
    "api_number": {"unit": "id", "qualifiers": ["none"], "context": None, "description": "API well number exactly as written"},
    "ground_elevation": {"unit": "ft", "qualifiers": ["actual"], "context": None, "description": "ground elevation above sea level"},
    "casing_depth": {"unit": "ft", "qualifiers": ["actual", "planned"], "context": "casing_size_in",
                     "description": "setting depth of one casing or liner string; casing_size_in is its outer diameter like 8-5/8"},
    "max_measured_temperature": {"unit": "degF", "qualifiers": ["actual"], "context": "depth_ft",
                                 "description": "the maximum temperature measured in the well, with its depth"},
    "projected_formation_temperature": {"unit": "degF", "qualifiers": ["projected"], "context": "depth_ft",
                                        "description": "calculated or projected equilibrium formation temperature at a depth"},
    "inclination": {"unit": "deg", "qualifiers": ["actual"], "context": "depth_ft",
                    "description": "survey inclination in degrees at a measured depth"},
    "productive_time": {"unit": "hours", "qualifiers": ["actual"], "context": None, "description": "total productive rig time"},
    "non_productive_time": {"unit": "hours", "qualifiers": ["actual"], "context": None, "description": "total non-productive rig time"},
    "total_rig_time": {"unit": "hours", "qualifiers": ["actual"], "context": None, "description": "total rig time"},
}
QUALIFIERS = sorted({q for p in PROPERTIES.values() for q in p["qualifiers"]})
UNITS = sorted({p["unit"] for p in PROPERTIES.values()})
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {"claims": {"type": "array", "maxItems": 20, "items": {
        "type": "object",
        "properties": {
            "well": {"type": "string"},
            "property": {"enum": sorted(PROPERTIES)},
            "qualifier": {"enum": QUALIFIERS},
            "value": {"type": "string"},
            "unit": {"enum": UNITS},
            "casing_size_in": {"type": ["string", "null"]},
            "depth_ft": {"type": ["number", "null"]},
            "quote": {"type": "string"},
        },
        "required": ["well", "property", "qualifier", "value", "unit", "casing_size_in", "depth_ft", "quote"],
    }}},
    "required": ["claims"],
}


def ontology_prompt() -> str:
    lines = [f"- {name} ({spec['unit']}; qualifier: {'/'.join(spec['qualifiers'])}"
             + (f"; requires {spec['context']}" if spec["context"] else "") + f"): {spec['description']}"
             for name, spec in PROPERTIES.items()]
    return "\n".join(lines)


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def number(value: Any) -> float | None:
    """Read the first number, tolerating thousands separators and attached units ("1,955 feet", "329°F")."""
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return round(float(match.group()), 6) if match else None


def casing_key(size: str | None) -> str | None:
    if not size:
        return None
    match = re.search(r"(\d+)[\s-]*(\d+/\d+)|(\d+(?:\.\d+)?)", size.replace("½", " 1/2"))
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}" if match.group(1) else match.group(3)


def well_key(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", name.upper().replace("WELL", "").replace("AKUTAN", ""))


def validate_claim(claim: dict[str, Any], chunk_text: str) -> str | None:
    """Return None if the claim passes, otherwise the reason it is rejected."""
    spec = PROPERTIES.get(claim.get("property"))
    if spec is None:
        return "unknown property"
    if claim.get("unit") != spec["unit"]:
        return "unit does not match property"
    if claim.get("qualifier") not in spec["qualifiers"]:
        return "qualifier not allowed for property"
    if spec["context"] == "casing_size_in" and not casing_key(claim.get("casing_size_in")):
        return "missing casing size"
    if spec["context"] == "depth_ft" and claim.get("depth_ft") is None:
        return "missing depth"
    quote = squash(claim.get("quote") or "")
    if len(quote) < 3 or quote not in squash(chunk_text):
        return "quote not found verbatim in chunk"
    value, plain_quote = claim.get("value") or "", quote.replace(",", "")
    if spec["unit"] == "date":
        match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value)
        if not match or MONTHS[int(match.group(2)) - 1] not in quote.lower() or str(int(match.group(3))) not in quote:
            return "date not supported by quote"
        if match.group(1) not in chunk_text:
            return "date year not in passage"
    elif spec["unit"] == "id":
        if re.sub(r"\D", "", value) not in re.sub(r"\D", "", quote) or not re.sub(r"\D", "", value):
            return "identifier not in quote"
    else:
        parsed = number(value)
        if parsed is None:
            return "value is not a number"
        if len(re.findall(r"\d+(?:\.\d+)?", value.replace(",", ""))) != 1:
            return "value must be a single number"
        candidates = {number(token) for token in re.findall(r"\d+(?:\.\d+)?", plain_quote)}
        if parsed not in candidates:
            return "value not in quote"
    return None


def same_value(a: Any, b: Any) -> bool:
    """Compare a claimed value with a gold value: numbers within 0.5%, dates and identifiers exactly."""
    if isinstance(b, str):
        return re.sub(r"\W", "", str(a)).lower() == re.sub(r"\W", "", b).lower()
    x = number(a)
    return x is not None and abs(x - b) <= max(0.01, 0.005 * abs(b))


def matches_gold(claim: dict[str, Any], fact: dict[str, Any]) -> bool:
    if well_key(claim["well"]) != well_key(fact["well"]) or claim["property"] != fact["property"]:
        return False
    if claim["qualifier"] != fact["qualifier"]:
        return False
    if "casing_size_in" in fact and casing_key(claim.get("casing_size_in")) != fact["casing_size_in"]:
        return False
    if "depth_ft" in fact and (claim.get("depth_ft") is None or abs(float(claim["depth_ft"]) - fact["depth_ft"]) > 1):
        return False
    return any(same_value(claim["value"], v) for v in [fact["value"], *fact.get("alternatives", [])])
