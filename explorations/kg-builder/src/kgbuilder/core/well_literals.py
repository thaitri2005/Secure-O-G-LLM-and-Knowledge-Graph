"""Shared pre-registered literal spans and guideline-derived status phrases."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from kgbuilder.core.config import ConfigError
from kgbuilder.core.well_values import NUMBER, DEPTH_UNIT, hash_is_pressure, in_name, parse_quantity, parse_us_date


QUANTITY_KINDS = ("interval", "depth", "pressure", "density", "size", "volume")
DATE_PATTERNS: tuple[str, ...] = (
    r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", r"\b\d{1,2}-\d{1,2}-(?:\d{4}|\d{2})\b",
    r"\b[A-Za-z]+\s+(?:\d{1,2},?\s+)?\d{4}\b", r"\b\d{4}-\d{2}-\d{2}\b", r"\b\d{4}\b",
)
_REFERENCE = r"(?:\s*(?:MD|TVD|BML|AML|SLM|CTM|WLM|DPM|KBM|RKB|KB)\b)*"
_PATTERNS = {
    "depth": rf"{NUMBER}\s*{DEPTH_UNIT}{_REFERENCE}",
    "interval": rf"{NUMBER}\s*(?:'|ft|feet|m)?\s*(?:MD|TVD)?\s*(?:-|to)\s*{NUMBER}\s*(?:'|ft\b|feet\b|m\b){_REFERENCE}",
    "pressure": rf"{NUMBER}\s*(?:psig?\b|#)",
    "density": rf"{NUMBER}\s*(?:ppg\b|lb/gal\b|EMW\b)",
    "volume": rf"{NUMBER}\s*(?:bbls?\b|sx\b|cu\s*ft\b|gal(?:lons?)?\b)",
    "size": rf'(?:\d+[- ]\d+/\d+|{NUMBER})\s*(?:"|in\b|inch(?:es)?\b)',
}


def typed_spans(surface: str, kinds) -> list[tuple[int, int, str]]:
    """Keep valid, unambiguous spans; overlapping hits retain the longest one."""
    hits = []
    for kind in kinds:
        patterns = DATE_PATTERNS if kind == "date" else (_PATTERNS[kind],)
        for pattern in patterns:
            for hit in re.finditer(r"(?<![\w.,/+-])" + pattern, surface, re.I):
                start, end = hit.span()
                if kind == "date":
                    valid = parse_us_date(hit[0])[1] != "partial"
                else:
                    valid = parse_quantity(hit[0], kind).status == "ok"
                if not valid: continue
                if kind in {"depth", "interval"} and in_name(surface, start, end): continue
                if kind == "size" and (re.search(r"\d\s*[xX]\s*$", surface[:start])
                                       or re.match(r"\s*[xX]\s*\d", surface[end:])): continue
                if kind == "pressure" and "#" in hit[0] and not hash_is_pressure(surface): continue
                hits.append((start, end, hit[0]))
    kept = []
    for hit in sorted(set(hits), key=lambda h: (-(h[1] - h[0]), h[0], h[2])):
        if not any(hit[0] < other[1] and other[0] < hit[1] for other in kept): kept.append(hit)
    return sorted(kept)


def typed_surface(surface: str, kinds) -> str | None:
    """Return the sole distinct literal text, leaving ambiguous surfaces alone."""
    values = {text.strip() for _, _, text in typed_spans(surface, kinds)}
    return next(iter(values)) if len(values) == 1 else None


def status_code(surface: str, lexicon: dict[str, list[str]]) -> str | None:
    """Match bare codes case-sensitively and phrases by the frozen case rule."""
    codes = {code for code, phrases in lexicon.items() if any(
        re.search(r"(?<![A-Za-z0-9])" + re.escape(phrase) + r"(?![A-Za-z0-9])", surface,
                  re.I if re.search(r"[a-z]", phrase) else 0) for phrase in phrases)}
    return next(iter(codes)) if len(codes) == 1 else None


class _Lexicon(dict):
    """Retain file provenance without adding a lexicon key or changing its hash."""
    def __init__(self, values, source):
        super().__init__(values)
        self.source = source


def load_lexicon(path: Path) -> dict:
    """Load the required lexicon shape without accepting malformed phrases."""
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not {"version", "status", "tubular_heads"} <= value.keys(): raise ValueError()
        if not isinstance(value["status"], dict) or not isinstance(value["tubular_heads"], list): raise ValueError()
        for phrases in [*value["status"].values(), value["tubular_heads"]]:
            if not isinstance(phrases, list) or not all(isinstance(p, str) and p for p in phrases): raise ValueError()
        return _Lexicon(value, path)
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        raise ConfigError("invalid literal lexicon") from exc
