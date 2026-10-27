"""Convert raw cell values into typed values according to a column specification."""
from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any
import unicodedata

TYPES = {"string", "integer", "decimal", "date", "datetime", "boolean"}
INTEGER = re.compile(r"[-+]?\d+")
DECIMAL = re.compile(r"[-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?")


class ValueProblem(ValueError):
    pass


def parse_value(spec: dict[str, Any], raw: Any) -> Any:
    """Return the typed value, or None for null; raise ValueProblem for malformed input.

    Strings from text files arrive stripped; spreadsheet cells may already be numbers or dates.
    """
    kind = spec["type"]
    if raw is None:
        return None
    if isinstance(raw, str):
        if raw in spec.get("null_values", ("",)):
            return None
        if kind == "string":
            # Windows-1258 and some exports write Vietnamese tone marks as combining characters.
            value = unicodedata.normalize("NFC", raw)
        elif kind == "integer":
            text = raw.replace(spec.get("thousands", "\0"), "")
            if not INTEGER.fullmatch(text):
                raise ValueProblem(f"expected an integer, found {raw!r}")
            value = int(text)
        elif kind == "decimal":
            text = raw.replace(spec.get("thousands", "\0"), "").replace(spec.get("decimal_mark", "."), ".")
            if not DECIMAL.fullmatch(text):
                raise ValueProblem(f"expected a decimal number, found {raw!r}")
            value = float(text)
        elif kind in ("date", "datetime"):
            value = None
            for pattern in spec.get("formats", ["%Y-%m-%d"]):
                try:
                    parsed = datetime.strptime(raw, pattern)
                except ValueError:
                    continue
                # strptime accepts unpadded numbers; require the round trip to match exactly.
                if parsed.strftime(pattern) == raw:
                    value = parsed.date().isoformat() if kind == "date" else parsed.isoformat()
                    break
            if value is None:
                raise ValueProblem(f"expected a {kind} in {spec.get('formats', ['%Y-%m-%d'])}, found {raw!r}")
        elif kind == "boolean":
            if raw in spec.get("true_values", ["true", "1", "yes"]):
                value = True
            elif raw in spec.get("false_values", ["false", "0", "no"]):
                value = False
            else:
                raise ValueProblem(f"expected a boolean, found {raw!r}")
        else:
            raise ValueProblem(f"unknown type {kind!r}")
    else:
        value = native_value(kind, raw)
    if "values" in spec and value not in spec["values"]:
        raise ValueProblem(f"{value!r} is not one of the allowed values")
    if "pattern" in spec and isinstance(value, str) and not re.fullmatch(spec["pattern"], value):
        raise ValueProblem(f"{value!r} does not match {spec['pattern']}")
    if "min" in spec and value < spec["min"] or "max" in spec and value > spec["max"]:
        raise ValueProblem(f"{value!r} is outside [{spec.get('min')}, {spec.get('max')}]")
    return value


def native_value(kind: str, raw: Any) -> Any:
    """Accept values a spreadsheet reader already typed."""
    if kind == "string":
        return raw.isoformat() if isinstance(raw, (date, datetime)) else str(raw)
    if kind == "integer" and isinstance(raw, (int, float)) and not isinstance(raw, bool) and float(raw).is_integer():
        return int(raw)
    if kind == "decimal" and isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    if kind == "date" and isinstance(raw, (date, datetime)):
        return (raw.date() if isinstance(raw, datetime) else raw).isoformat()
    if kind == "datetime" and isinstance(raw, datetime):
        return raw.isoformat()
    if kind == "boolean" and isinstance(raw, bool):
        return raw
    raise ValueProblem(f"expected {kind}, found {type(raw).__name__} {raw!r}")


def derive(spec: dict[str, Any], record: dict[str, Any]) -> Any:
    """Compute a derived field from already parsed fields; None input gives None."""
    operation = spec["op"]
    if operation == "template":
        try:
            return spec["template"].format_map(TemplateValues(record))
        except MissingValue:
            return None
    value = record.get(spec["from"])
    if value is None:
        return None
    text = str(value)
    if operation == "slice":
        return text[spec.get("start", 0):spec.get("end")]
    if operation == "strip_leading_zeros":
        return re.sub(r"^0+(?=.)", "", text)
    if operation == "digits":
        return re.sub(r"\D", "", text) or None
    if operation == "upper":
        return text.upper()
    if operation == "lower":
        return text.lower()
    raise ValueError(f"unknown derivation {operation!r}")


class MissingValue(KeyError):
    pass


class TemplateValues(dict):
    """format_map source that refuses null or absent fields, so templates never render 'None'."""

    def __init__(self, record: dict[str, Any]):
        super().__init__(record)

    def __missing__(self, key: str) -> Any:
        raise MissingValue(key)

    def __getitem__(self, key: str) -> Any:
        value = super().__getitem__(key)
        if value is None or value == "":
            raise MissingValue(key)
        return value


def render(template: str, record: dict[str, Any]) -> str | None:
    try:
        return template.format_map(TemplateValues(record))
    except MissingValue:
        return None
