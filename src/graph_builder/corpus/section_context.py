"""Decide which section headings of a document carry no section information (page banners, date stamps, e-mail addresses).

Docling labels any prominent line a section header. On reports with a running page header, the banner of every page
("Daily Drilling Report Well ID: AK-3") or a report-date stamp then becomes the ``section`` of the passages under it.
This module recognises such values from the PDF text layer (repetition inside the header or footer band of many pages)
and from configured value patterns. The K1 builder removes the recognised values from ``section`` and ``section_path``
only; section parents and chunk ids are not changed. Without evidence nothing is removed.

Optionally (``numbered_hierarchy``) a numbered heading ("VI.1 Drilling BHA 18") gets as ancestors the headings of the
same document that carry the number prefix ("VI. Drilling Operations ...") and were seen before it; Docling reports
every heading at the same level, so ``section_path`` is otherwise flat. Ancestors that do not exist are not invented.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
from typing import Any, Iterable

FURNITURE_KEYS = {"header_band_page_height", "footer_band_page_height", "min_pages", "min_page_share"}


def normalise(value: str, mask_numbers: bool = False) -> str:
    """Lower-case alphanumeric words joined by one space; makes text-layer lines and Docling headings comparable.

    With ``mask_numbers`` every word that contains a digit becomes ``#``, so a banner that carries a changing
    number or date ("Summary 21 Aug 16") is the same line on every page.
    """
    words = re.findall(r"[^\W_]+", value.lower())
    return " ".join("#" if mask_numbers and any(ch.isdigit() for ch in word) else word for word in words)


def validate_section_context(config: Any) -> dict[str, Any]:
    if not isinstance(config, dict) or not {"furniture", "value_patterns"} <= set(config) <= {"furniture", "value_patterns", "numbered_hierarchy"}:
        raise ValueError("section_context must contain furniture, value_patterns and optionally numbered_hierarchy")
    furniture = config["furniture"]
    if not isinstance(furniture, dict) or set(furniture) != FURNITURE_KEYS:
        raise ValueError(f"section_context furniture must contain exactly {sorted(FURNITURE_KEYS)}")
    for key in ("header_band_page_height", "footer_band_page_height"):
        if type(furniture[key]) not in (int, float) or not 0 <= furniture[key] <= 0.3:
            raise ValueError(f"section_context furniture {key} must be a fraction of the page height between 0 and 0.3")
    if type(furniture["min_pages"]) is not int or furniture["min_pages"] < 2:
        raise ValueError("section_context furniture min_pages must be an integer of at least 2")
    if type(furniture["min_page_share"]) not in (int, float) or not 0 < furniture["min_page_share"] <= 1:
        raise ValueError("section_context furniture min_page_share must be a fraction between 0 and 1")
    patterns = config["value_patterns"]
    if not isinstance(patterns, list) or any(
            not isinstance(item, dict) or set(item) != {"kind", "pattern"} or not isinstance(item["kind"], str)
            or not item["kind"] or not isinstance(item["pattern"], str) or not item["pattern"] for item in patterns):
        raise ValueError("section_context value_patterns must be a list of {kind, pattern} objects")
    for item in patterns:
        try:
            re.compile(item["pattern"])
        except re.error as error:
            raise ValueError(f"section_context value_patterns contains an invalid regular expression: {error}") from error
    if "numbered_hierarchy" in config:
        compile_numbering(config["numbered_hierarchy"])
    return config


def compile_numbering(schemes: Any) -> list[tuple[str, re.Pattern[str]]]:
    """Compile ``numbered_hierarchy``: a list of {scheme, pattern}; the pattern has one group holding the dotted number."""
    if not isinstance(schemes, list) or not schemes or any(
            not isinstance(item, dict) or set(item) != {"scheme", "pattern"} or not isinstance(item["scheme"], str)
            or not item["scheme"] or not isinstance(item["pattern"], str) for item in schemes):
        raise ValueError("section_context numbered_hierarchy must be a non-empty list of {scheme, pattern} objects")
    if len({item["scheme"] for item in schemes}) != len(schemes):
        raise ValueError("section_context numbered_hierarchy schemes must differ")
    compiled = []
    for item in schemes:
        try:
            pattern = re.compile(item["pattern"])
        except re.error as error:
            raise ValueError(f"section_context numbered_hierarchy contains an invalid regular expression: {error}") from error
        if pattern.groups != 1:
            raise ValueError("section_context numbered_hierarchy patterns need exactly one capture group (the dotted number)")
        compiled.append((item["scheme"], pattern))
    return compiled


def number_key(heading: str, schemes: list[tuple[str, re.Pattern[str]]]) -> tuple[str, tuple[str, ...]] | None:
    """(scheme, dotted number parts) of a numbered heading, or None; the first scheme that matches wins."""
    for scheme, pattern in schemes:
        found = pattern.match(heading.strip())
        if found:
            return scheme, tuple(found.group(1).split("."))
    return None


def hierarchy_path(heading: str, seen: dict, schemes: list[tuple[str, re.Pattern[str]]]) -> list[str]:
    """Section path of a heading: earlier headings with a shorter prefix of its number, then the heading itself.

    ``seen`` maps number keys to the latest heading carrying them in this document and is updated here. Unnumbered
    headings, and numbered ones whose ancestors were not seen, keep the flat path [heading].
    """
    key = number_key(heading, schemes)
    if key is None:
        return [heading]
    scheme, parts = key
    seen[key] = heading
    return [seen[(scheme, parts[:size])] for size in range(1, len(parts)) if (scheme, parts[:size]) in seen] + [heading]


def band_boxes(width: float, height: float, rotation: int, fraction_top: float, fraction_bottom: float) -> dict[str, tuple]:
    """Header and footer rectangles (left, bottom, right, top) in unrotated PDF page space for the page as displayed.

    ``width`` and ``height`` are the unrotated page size. The displayed top edge is the page top for rotation 0, the
    left edge for 90, the bottom for 180 and the right edge for 270 (clockwise display rotation).
    """
    if rotation == 0:
        return {"header": (0, height * (1 - fraction_top), width, height), "footer": (0, 0, width, height * fraction_bottom)}
    if rotation == 90:
        return {"header": (0, 0, width * fraction_top, height), "footer": (width * (1 - fraction_bottom), 0, width, height)}
    if rotation == 180:
        return {"header": (0, 0, width, height * fraction_top), "footer": (0, height * (1 - fraction_bottom), width, height)}
    return {"header": (width * (1 - fraction_top), 0, width, height), "footer": (0, 0, width * fraction_bottom, height)}


def band_lines(pdf_path: Path, pages: Iterable[int], furniture: dict[str, Any]) -> dict[int, list[str]]:
    """Normalised text lines of the header and footer bands of each 1-based page, in reading order.

    Unreadable pages and pages whose display is rotated are skipped: the line order of rotated text in the text
    layer is not reliable, so such pages never provide banner evidence.
    """
    import pypdfium2 as pdfium
    lines: dict[int, list[str]] = {}
    with pdfium.PdfDocument(pdf_path) as pdf:
        for number in pages:
            try:
                page = pdf[number - 1]
                try:
                    textpage = page.get_textpage()
                    try:
                        rotation = page.get_rotation()
                        if rotation != 0:
                            continue
                        width, height = page.get_size()
                        found = []
                        boxes = band_boxes(width, height, rotation, furniture["header_band_page_height"],
                                           furniture["footer_band_page_height"])
                        for name in ("header", "footer"):
                            left, bottom, right, top = boxes[name]
                            if (right - left) * (top - bottom) <= 0:
                                continue
                            text = textpage.get_text_bounded(left=left, bottom=bottom, right=right, top=top)
                            found.extend(line for line in (normalise(part, True) for part in re.split(r"[\r\n]+", text)) if line)
                        lines[number] = found
                    finally:
                        textpage.close()
                finally:
                    page.close()
            except Exception:
                continue  # one unreadable page must not stop the document
    return lines


def furniture_values(lines: dict[int, list[str]], furniture: dict[str, Any]) -> set[tuple[str, ...]]:
    """Return the banner of a document: the distinct reading-order sequences of its banner lines.

    A band line is banner furniture when it occurs in the bands of at least ``min_pages`` pages and at least
    ``min_page_share`` of the readable pages. Documents with fewer pages than ``min_pages`` have none.
    """
    pages_with = Counter(line for page_lines in lines.values() for line in set(page_lines))
    needed = max(furniture["min_pages"], furniture["min_page_share"] * len(lines))
    repeated = {line for line, count in pages_with.items() if count >= needed}
    return {sequence for sequence in (tuple(line for line in page_lines if line in repeated) for page_lines in lines.values()) if sequence}


def is_banner(heading: str, banner: set[tuple[str, ...]]) -> bool:
    """True when the heading is made of banner lines.

    Docling joins the pieces of a multi-line banner into one heading and may cut each piece. The heading must be a
    concatenation of beginnings of banner lines of one page in reading order (lines may be skipped). A beginning is a
    whole line or at least two words (not only numbers); a single word must equal a whole banner line. A heading that
    is only a slice from the middle of a banner line ("Lessons Learned" inside "End of Well Report and Lessons
    Learned ...") is not a banner.
    """
    tokens = normalise(heading, True).split()
    for sequence in banner:
        position = 0
        for line in sequence:
            if position >= len(tokens):
                break
            words = line.split()
            size = 0
            while size < len(words) and position + size < len(tokens) and words[size] == tokens[position + size]:
                size += 1
            if (size == len(words) or size >= 2) and any(word != "#" for word in words[:size]):
                position += size
        if position == len(tokens):
            return True
    return False

def classify_sections(sections: Iterable[str], banner: set[tuple[str, ...]], patterns: list[dict]) -> dict[str, str]:
    """Map each section heading that is not a real section to its kind: ``banner`` or the kind of the first matching value pattern."""
    compiled = [(item["kind"], re.compile(item["pattern"])) for item in patterns]
    result = {}
    for section in sorted(set(sections)):
        kind = next((name for name, pattern in compiled if pattern.search(section.strip())), None)
        if kind is None and normalise(section) and is_banner(section, banner):
            kind = "banner"
        if kind:
            result[section] = kind
    return result

def non_section_values(pdf_path: Path, pages: list[int], sections: Iterable[str], config: dict[str, Any]) -> dict[str, str]:
    """Return {section heading: kind} for the headings of one document that carry no section information."""
    furniture = config["furniture"]
    banner = furniture_values(band_lines(pdf_path, pages, furniture), furniture)
    return classify_sections(sections, banner, config["value_patterns"])

def clean_path(path: list[str], dropped: dict[str, str]) -> list[str]:
    """The section path without the headings recognised as non-sections; order is kept."""
    return [heading for heading in path if heading not in dropped]
