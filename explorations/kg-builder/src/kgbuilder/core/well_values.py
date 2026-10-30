"""Conservative well-operation quantities and dates, without implicit conversions."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from fractions import Fraction


RELATIONS = (
    "spudded_on", "reached_td", "drilled_to", "set_casing_at", "casing_size",
    "casing_spec", "cemented_interval", "set_plug_at", "set_equipment_at", "tagged_at",
    "cut_at", "tested_to_pressure", "fit_lot_emw", "perforated_interval", "has_mud_weight",
    "completed_in", "encountered_marker", "has_well_status", "used_rig", "operated_by", "pumped",
)
NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
DEPTH_UNIT = r"(?:'|ft\b|feet\b|m\b|meters?\b)"


@dataclass(frozen=True)
class Quantity:
    """A literal with its original surface and explicit measurement semantics."""
    kind: str
    value: str | None
    lower: str | None
    upper: str | None
    unit: str
    reference: str
    datum: str
    raw: str
    status: str


def decimal(value: str) -> str:
    """Canonical finite decimal, keeping zero exact."""
    number = Decimal(value.replace(",", ""))
    if not number.is_finite():
        raise ValueError("non-finite quantity")
    return format(number.normalize(), "f")


def hash_is_pressure(text: str) -> bool:
    """Apply the guideline pressure-word context to ambiguous hash signs."""
    return "#" not in text or bool(re.search(r"\b(?:psi|psig|test\w*|bleed|bled|pressure\w*)\b", text, re.I))


def in_name(text: str, start: int, end: int) -> bool:
    """Identify quantity spans immediately followed by a geologic name head."""
    return bool(re.match(r"\s*(?:sand|zone|reservoir|formation)\b", text[end:], re.I))


def parse_quantity(surface: str, kind: str | None = None) -> Quantity:
    """Parse one quantity, never guessing units or repairing damaged punctuation."""
    raw = surface
    text = surface.strip()
    unit = reference = datum = "unknown"
    value = lower = upper = None
    status = "unparsed"
    if kind is None:
        for candidate in ("interval", "depth", "pressure", "density", "size", "volume"):
            if candidate == "pressure" and not hash_is_pressure(text):
                continue
            parsed = parse_quantity(text, candidate)
            if parsed.status == "ok":
                return parsed
        kind = "depth"
    ref = re.search(r"\b(MD|TVD|BML|AML|SLM|CTM|WLM|DPM|KBM|RKB|KB)\b", text, re.I)
    if ref:
        token = ref[1].upper()
        if token in {"MD", "TVD"}: reference = token
        elif token in {"BML", "AML"}: reference, datum = token, "ML"
        elif token in {"SLM", "CTM", "WLM", "DPM"}: reference, datum = "MD", token
        else: datum = "KB"
    if kind in {"depth", "interval"}:
        if re.search(r"'|(?:\b|(?<=\d))(?:ft|feet)\b", text, re.I): unit = "ft"
        elif re.search(r"(?:\b|(?<=\d))(?:m|meters?)\b", text, re.I): unit = "m"
        interval = re.search(rf"({NUMBER})\s*(?:{DEPTH_UNIT})?\s*(?:MD|TVD)?\s*(?:-|to)\s*({NUMBER})", text, re.I)
        if kind == "interval" and interval:
            lo, hi = (v.replace(",", "") for v in interval.groups())
            if "." not in lo + hi and len(hi) < len(lo):
                hi = lo[:-len(hi)] + hi
                if int(hi) < int(lo): hi = str(int(hi) + 10 ** len(interval[2].replace(",", "")))
            lower, upper = sorted((decimal(lo), decimal(hi)), key=Decimal)
        elif kind == "depth" and not interval:
            hit = re.fullmatch(rf"({NUMBER})\s*(?:{DEPTH_UNIT}|\u00bf)?\s*(?:(?:MD|TVD|BML|AML|SLM|CTM|WLM|DPM|KBM|RKB|KB)\s*)*", text, re.I)
            if hit: value = decimal(hit[1])
    elif kind == "size":
        if re.search(rf"{NUMBER}\s*[xX]\s*{NUMBER}", text):
            return Quantity(kind, None, None, None, unit, reference, datum, raw, "unparsed")
        hit = re.search(r'(\d+)(?:[- ](\d+)/(\d+))\s*(?:"|in\b|inch(?:es)?\b)', text, re.I)
        if hit:
            if int(hit[3]):
                fraction = Fraction(int(hit[1])) + Fraction(int(hit[2]), int(hit[3]))
                value = decimal(str(Decimal(fraction.numerator) / Decimal(fraction.denominator)))
                unit = "in"
        else:
            hit = re.search(rf'({NUMBER})\s*(?:"|in\b|inch(?:es)?\b)', text, re.I)
            if hit: value, unit = decimal(hit[1]), "in"
    elif kind in {"pressure", "density", "volume"}:
        suffix = {"pressure": r"(?:psig?\b|#)", "density": r"(?:ppg\b|lb/gal\b|EMW\b)",
                  "volume": r"(?:bbls?\b|sx\b|cu\s*ft\b|gal(?:lons?)?\b)"}[kind]
        hit = re.search(rf"({NUMBER})\s*({suffix})", text, re.I)
        if hit:
            value = decimal(hit[1])
            token = hit[2].lower()
            unit = "psi" if kind == "pressure" else "ppg" if kind == "density" else (
                "bbl" if token.startswith("bbl") else "cuft" if token.startswith("cu") else "gal" if token.startswith("gal") else "sx")
    if value is not None or lower is not None:
        status = "ok" if unit != "unknown" else "ambiguous"
    elif kind != "interval" and re.fullmatch(NUMBER, text):
        value, status = decimal(text), "ambiguous"
    if "\u00bf" in text:
        unit, status = "unknown", "ambiguous"
    return Quantity(kind, value, lower, upper, unit, reference, datum, raw, status)


def parse_us_date(surface: str) -> tuple[str | None, str]:
    """US date order and an explicit 1950/2050 pivot; never supply a missing year."""
    text = surface.strip()
    try:
        for pattern in (r"(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?",
                        r"(\d{1,2})-(\d{1,2})(?:-(\d{2}|\d{4}))?"):
            numeric = re.fullmatch(pattern, text)
            if numeric is None:
                continue
            month, day = int(numeric[1]), int(numeric[2])
            year_text = numeric[3]
            if year_text is None:
                date(2000, month, day)
                return None, "partial"
            year = int(year_text)
            if len(year_text) == 2:
                year += 2000 if year < 50 else 1900
            return date(year, month, day).isoformat(), "day"
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return date.fromisoformat(text).isoformat(), "day"
        match = re.fullmatch(r"(?:(?:early|late|mid)\s+)?(\d{4})", text, re.I)
        if match:
            date(int(match[1]), 1, 1)
            return match[1], "year"
        months = {name: i + 1 for i, name in enumerate(("january", "february", "march", "april", "may", "june",
                  "july", "august", "september", "october", "november", "december"))}
        match = re.fullmatch(r"([A-Za-z]+)\s+(?:(\d{1,2})(?:st|nd|rd|th)?,?\s+)?(\d{4})", text, re.I)
        if match:
            month = months.get(match[1].lower())
            if month is None:
                month = next((n for name, n in months.items() if name[:3] == match[1].lower()), None)
            if month is None: return None, "partial"
            day = int(match[2]) if match[2] else 1
            parsed = date(int(match[3]), month, day).isoformat()
            return (parsed, "day") if match[2] else (parsed[:7], "month")
    except ValueError:
        pass
    # The guideline does not define a whitelist for partial date surfaces (A2).
    return None, "partial"


def compare(a: Quantity, b: Quantity, policy: dict, symmetric: bool = False) -> bool:
    """Compare like quantities under the frozen policy; no ft/m or MD/TVD conversion."""
    if a.kind != b.kind or a.status == "unparsed" or b.status == "unparsed": return False
    if a.reference != b.reference and "unknown" not in (a.reference, b.reference): return False
    if a.unit != b.unit and "unknown" not in (a.unit, b.unit): return False
    policy = policy.get("tolerance", policy)
    def same(x, y):
        if x is None or y is None: return False
        try: left, right = Decimal(x), Decimal(y)
        except InvalidOperation: return False
        if not left.is_finite() or not right.is_finite(): return False
        if "unknown" in (a.unit, b.unit): return left == right
        if a.kind in {"depth", "interval"}:
            return abs(left - right) <= Decimal(str(policy.get("depth_ft", 1))) if a.unit == "ft" else left == right
        if a.kind == "density": return abs(left - right) <= Decimal(str(policy.get("density_ppg", "0.05")))
        if a.kind in {"pressure", "volume"}:
            if left == 0 or right == 0: return left == right
            if symmetric:
                return abs(left - right) <= Decimal(str(policy.get(a.kind + "_relative", "0.01"))) * max(abs(left), abs(right))
            return abs(left - right) / abs(left) <= Decimal(str(policy.get(a.kind + "_relative", "0.01")))
        return left == right
    return same(a.lower, b.lower) and same(a.upper, b.upper) if a.kind == "interval" else same(a.value, b.value)
