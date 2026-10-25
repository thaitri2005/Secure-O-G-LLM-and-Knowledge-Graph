"""Describe and parse the delimited BSEE Data Center well files.

The delimited exports are quoted, header-less CSV files whose values keep their fixed-width
padding. A few delimited columns hold several adjacent fixed-width fields; for example the
borehole surface location "03707N07080W" is a distance, its N/S code, a distance and its E/W
code. Such columns are listed as tuples of (name, width, kind) parts. Layout sources:
https://www.data.bsee.gov/Main/HtmlPage.aspx?page=borehole and ?page=apiChanges.
"""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any

# Fields withheld by BSEE (for example depths before total depth or lease expiry) are filled
# with "#" (borehole) or "*" (API changes). They are reported as withheld, not as blank.
WITHHELD_CHARACTERS = ({"#"}, {"*"})
INTEGER = re.compile(r"-?\d+")
DECIMAL = re.compile(r"-?\d+(\.\d+)?")
API_NUMBER = re.compile(r"\d{12}")
# strptime accepts unpadded numbers, so the exact shape is checked first.
DATES = {"ymd": (re.compile(r"\d{8}"), "%Y%m%d"), "mdy": (re.compile(r"\d{2}/\d{2}/\d{4}"), "%m/%d/%Y")}

BOREHOLE = (
    ("api_well_number", "api"),
    ("well_name", "text"),
    ("well_name_suffix", "text"),
    ("operator_number", "text"),
    ("bottom_field_name_code", "text"),
    ("spud_date", "ymd"),
    ("bottom_lease_number", "text"),
    ("rkb_elevation_ft", "int"),
    ("bh_total_md_ft", "int"),
    ("tvd_ft", "int"),
    (("surface_ns_distance", 5, "int"), ("surface_ns_code", 1, "text"),
     ("surface_ew_distance", 5, "int"), ("surface_ew_code", 1, "text")),
    (("surface_area_code", 2, "text"), ("surface_block_number", 6, "text")),
    (("bottom_ns_distance", 5, "int"), ("bottom_ns_code", 1, "text"),
     ("bottom_ew_distance", 5, "int"), ("bottom_ew_code", 1, "text")),
    (("bottom_area_code", 2, "text"), ("bottom_block_number", 6, "text")),
    ("total_depth_date", "ymd"),
    ("status_date", "ymd"),
    ("type_code", "text"),
    ("district_code", "text"),
    ("status_code", "text"),
    ("water_depth_ft", "int"),
    ("surface_longitude", "decimal"),
    ("surface_latitude", "decimal"),
    ("bottom_longitude", "decimal"),
    ("bottom_latitude", "decimal"),
    ("surface_lease_number", "text"),
    ("complex_id", "text"),
    ("structure_number", "text"),
    ("update_date", "ymd"),
    ("well_class_code", "text"),
)

API_CHANGE = (
    ("api_well_number", "api"),
    ("activity_type_code", "text"),
    ("previous_api_number", "text"),
    ("activity_date", "mdy"),
    ("well_name", "text"),
    ("well_name_suffix", "text"),
    ("surface_lease_number", "text"),
    ("surface_area_code", "text"),
    ("surface_block_number", "text"),
    ("spud_date", "mdy"),
    ("bottom_lease_number", "text"),
    ("bottom_area_code", "text"),
    ("bottom_block_number", "text"),
    ("bh_total_md_ft", "int"),
)

LAYOUTS = {"borehole": BOREHOLE, "api_change": API_CHANGE}


def field_names(layout: tuple) -> list[str]:
    return [part[0] for column in layout for part in (column if isinstance(column[0], tuple) else (column,))]


def is_withheld(value: str) -> bool:
    return bool(value) and set(value) in WITHHELD_CHARACTERS


def parse_value(kind: str, value: str) -> Any:
    """Convert one stripped value; blank becomes None and malformed input raises ValueError."""
    if not value:
        return None
    if kind == "text":
        return value
    if kind == "api":
        if not API_NUMBER.fullmatch(value):
            raise ValueError(f"API well number must have 12 digits: {value!r}")
        return value
    if kind == "int":
        if not INTEGER.fullmatch(value):
            raise ValueError(f"expected an integer: {value!r}")
        return int(value)
    if kind == "decimal":
        if not DECIMAL.fullmatch(value):
            raise ValueError(f"expected a decimal number: {value!r}")
        return float(value)
    if kind in DATES:
        shape, pattern = DATES[kind]
        try:
            if not shape.fullmatch(value):
                raise ValueError
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            raise ValueError(f"expected a valid {pattern} date: {value!r}") from None
    raise ValueError(f"unknown field kind {kind!r}")


def parse_row(layout: tuple, row: list[str]) -> tuple[dict[str, Any], list[str]]:
    """Return typed values in layout order and the names of withheld fields."""
    if len(row) != len(layout):
        raise ValueError(f"expected {len(layout)} columns, found {len(row)}")
    values: dict[str, Any] = {}
    withheld: list[str] = []
    for column, raw in zip(layout, row):
        parts = column if isinstance(column[0], tuple) else ((column[0], None, column[1]),)
        stripped = raw.strip()
        if is_withheld(stripped):
            for name, _, _ in parts:
                values[name] = None
                withheld.append(name)
            continue
        if len(parts) > 1 and stripped and len(raw) != sum(width for _, width, _ in parts):
            raise ValueError(f"{parts[0][0]}: combined column has width {len(raw)}: {raw!r}")
        position = 0
        for name, width, kind in parts:
            piece = raw[position:position + width] if width else raw
            position += width or 0
            try:
                values[name] = parse_value(kind, piece.strip())
            except ValueError as error:
                raise ValueError(f"{name}: {error}") from None
    return values, withheld
