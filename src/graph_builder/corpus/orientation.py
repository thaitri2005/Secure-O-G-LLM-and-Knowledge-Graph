"""Page orientation: find pages whose text is not upright when displayed, and (optionally) convert them upright.

Problem class (C-03): a page can be displayed with its text turned by 90, 180 or 270 degrees, either because ``/Rotate``
turns upright text sideways or because the text is drawn sideways and no ``/Rotate`` compensates. Docling's layout and
table models work on the displayed page and are trained on upright pages, so a sideways page changes the table and reading
structure without any signal. A page with ``/Rotate`` whose text is upright when displayed is NOT affected.

What is measured: the direction of the glyph baseline in the page's own coordinate space (PDFium character origins of
consecutive glyphs), turned by ``/Rotate``. ``displayed`` = text direction clockwise from "left to right" in degrees.

States (``classify``): ``upright`` (SUPPORTED), ``sideways`` (``rotated_page``: fixable by a working copy), ``mixed`` and
``no_text_rotated`` (``rotated_page``, UNSUPPORTED: the direction cannot be decided), ``no_text`` (nothing to judge),
``failed`` (PARSING FAILURE, reason recorded). Nothing here claims that a conversion is correct.

``normalize_working_copy`` writes a copy with a changed ``/Rotate`` for the sideways pages; the original PDF is never
modified. Page boxes and regions of the converted document then use the upright page frame.
"""
from __future__ import annotations

import ctypes
from collections import Counter
from dataclasses import dataclass, field
import math
from pathlib import Path
import re
from typing import Any, Callable
import unicodedata

MODES = ("flag", "normalize", "verify")
DEFAULT_SETTINGS = {
    "min_chars": 40,           # fewer measured glyph steps: the direction is not judged
    "dominant_share": 0.8,     # share of glyph steps that must point the same way
    "angle_tolerance": 10.0,   # degrees; steps further from a multiple of 90 count as oblique
    "max_steps": 4000,         # glyph steps measured per page (evenly strided, deterministic)
}
REASON = "rotated_page"


def orientation_settings(supplied: Any) -> dict[str, Any]:
    """Validate the orientation mode and glyph-direction thresholds."""
    if not isinstance(supplied, dict) or "mode" not in supplied or set(supplied) - set(DEFAULT_SETTINGS) - {"mode"}:
        raise ValueError(f"analysis.page_orientation needs mode {list(MODES)} and optionally {sorted(DEFAULT_SETTINGS)}")
    if supplied["mode"] not in MODES:
        raise ValueError(f"analysis.page_orientation.mode must be one of {list(MODES)}")
    settings = {**DEFAULT_SETTINGS, **supplied}
    if type(settings["min_chars"]) is not int or not 1 <= settings["min_chars"] <= 100000:
        raise ValueError("analysis.page_orientation.min_chars must be an integer from 1 to 100000")
    if type(settings["max_steps"]) is not int or not 100 <= settings["max_steps"] <= 1000000:
        raise ValueError("analysis.page_orientation.max_steps must be an integer from 100 to 1000000")
    if type(settings["dominant_share"]) not in (int, float) or not 0.5 < settings["dominant_share"] <= 1:
        raise ValueError("analysis.page_orientation.dominant_share must be above 0.5 and at most 1")
    if type(settings["angle_tolerance"]) not in (int, float) or not 0 < settings["angle_tolerance"] < 45:
        raise ValueError("analysis.page_orientation.angle_tolerance must be above 0 and below 45 degrees")
    return settings


def quarter(angle: float, tolerance: float) -> int | None:
    """Nearest multiple of 90 (0, 90, 180, 270) or None when the angle is further than ``tolerance`` from one."""
    nearest = round(angle / 90.0)
    return int(nearest) % 4 * 90 if abs(angle - nearest * 90.0) <= tolerance else None


def classify(rotation: int, steps: dict[int | None, int], settings: dict[str, Any], has_text_layer: bool = True) -> dict[str, Any]:
    """Pure decision. ``steps`` counts glyph steps per baseline direction in the page's own space (clockwise degrees,
    0 = left to right, ``None`` = oblique). Returns the orientation record stored with the page."""
    total = sum(steps.values())
    record: dict[str, Any] = {"rotation": rotation, "steps": total}
    if not has_text_layer or total < settings["min_chars"]:
        if rotation:
            return {**record, "state": "no_text_rotated", "status": "UNSUPPORTED_FORMAT", "reason": REASON,
                    "detail": "page has /Rotate and no measurable text layer; displayed orientation is unknown"}
        return {**record, "state": "no_text", "status": "SUPPORTED", "reason": None}
    direction, count = max(steps.items(), key=lambda item: (item[1], -(360 if item[0] is None else item[0])))  # ties: smaller angle
    if direction is None or count / total < settings["dominant_share"]:
        return {**record, "state": "mixed", "status": "UNSUPPORTED_FORMAT", "reason": REASON,
                "detail": "no single dominant text direction", "dominant_share": round(count / total, 3)}
    displayed = (direction + rotation) % 360
    record.update(text_direction=direction, displayed=displayed, dominant_share=round(count / total, 3))
    if displayed == 0:
        return {**record, "state": "upright", "status": "SUPPORTED", "reason": None}
    return {**record, "state": "sideways", "status": "UNSUPPORTED_FORMAT", "reason": REASON,
            "correction_rotate": (-direction) % 360}


def measure_steps(textpage: Any, settings: dict[str, Any]) -> dict[int | None, int]:
    """Count glyph-to-glyph steps along a line by baseline direction. Steps between consecutive visible glyphs whose
    distance is about one glyph (up to ``3 x`` the larger box side) are used; line jumps and spaces are ignored."""
    from pypdfium2 import raw
    count = textpage.count_chars()
    stride = max(1, count // settings["max_steps"])
    steps: dict[int | None, int] = {}
    x, y = ctypes.c_double(), ctypes.c_double()

    def glyph(index: int):
        if not textpage.get_text_range(index, 1).strip() or not raw.FPDFText_GetCharOrigin(textpage.raw, index, x, y):
            return None
        left, bottom, right, top = textpage.get_charbox(index, loose=True)
        return (x.value, y.value), max(right - left, top - bottom, 1.0)

    for index in range(0, count - 1, stride):
        first, second = glyph(index), glyph(index + 1)
        if first is None or second is None:
            continue
        dx, dy = second[0][0] - first[0][0], second[0][1] - first[0][1]
        distance = math.hypot(dx, dy)
        if 0.05 < distance <= 3 * first[1]:
            direction = quarter(-math.degrees(math.atan2(dy, dx)), settings["angle_tolerance"])  # y up -> clockwise
            steps[direction] = steps.get(direction, 0) + 1
    return steps


def analyze_orientation(path: Path, settings: dict[str, Any], skip_pages: set[int] | frozenset = frozenset()) -> dict[int, dict[str, Any]]:
    """Orientation record of every page (1-based) of a PDF. A page that cannot be read gets state ``failed`` with the
    exception name; pages in ``skip_pages`` (OCR pages: the text layer is not trusted) are ``not_assessed``."""
    import pypdfium2
    records: dict[int, dict[str, Any]] = {}
    with pypdfium2.PdfDocument(path) as pdf:
        for index in range(len(pdf)):
            number = index + 1
            page = pdf[index]
            try:
                rotation = int(page.get_rotation())
                if number in skip_pages:
                    records[number] = ({"rotation": rotation, "state": "no_text_rotated", "status": "UNSUPPORTED_FORMAT", "reason": REASON,
                                        "detail": "OCR page: text layer not used; displayed orientation is unknown", "steps": 0}
                                       if rotation else {"rotation": rotation, "state": "not_assessed", "status": "SUPPORTED",
                                                         "reason": None, "steps": 0})
                    continue
                textpage = page.get_textpage()
                try:
                    steps = measure_steps(textpage, settings)
                finally:
                    textpage.close()
                records[number] = classify(rotation, steps, settings)
            except Exception as error:  # noqa: BLE001 - one unreadable page never stops the document
                records[number] = {"state": "failed", "status": "PARSING_FAILURE", "reason": "orientation_unreadable",
                                   "detail": f"{type(error).__name__}: {str(error)[:120]}"}
            finally:
                page.close()
    return records


UPRIGHT_COPY = "input-upright.pdf"


def normalized_rotation(page: dict) -> tuple[int, int] | None:
    """Return the source and conversion rotations recorded for a normalized page."""
    orientation = page.get("orientation") or {}
    original, working = page.get("rotation"), orientation.get("applied_rotate")
    if (orientation.get("normalized") is True and orientation.get("rotation") == original
            and original in (0, 90, 180, 270) and working in (0, 90, 180, 270) and original != working):
        return original, working
    return None


def rotate_bbox(box: list[float], width: float, height: float, degrees: int) -> list[float]:
    """Rotate a top-left page box clockwise around the displayed page."""
    left, top, right, bottom = box
    return {
        0: [left, top, right, bottom],
        90: [height - bottom, left, height - top, right],
        180: [width - right, height - bottom, width - left, height - top],
        270: [top, width - right, bottom, width - left],
    }[degrees % 360]


def apply_page_orientation(source: Path, directory: Path, analysis: list[dict[str, Any]], settings: dict[str, Any]) -> Path:
    """Attach ``orientation`` to every page dict of ``analysis`` and return the file Docling must convert.

    ``flag`` returns ``source``. ``normalize`` and ``verify`` prepare an upright copy when at least one page has
    a correction. The caller compares that preliminary copy in ``verify`` mode. Failed copies keep the source."""
    skipped = ("ocr", "hybrid") if settings["mode"] == "verify" else ("ocr",)
    records = analyze_orientation(source, settings, {page["page"] for page in analysis if page.get("mode") in skipped})
    conversion_source, corrected = source, []
    if settings["mode"] in ("normalize", "verify"):
        try:
            corrected = normalize_working_copy(source, directory / UPRIGHT_COPY, records)
            if corrected:
                conversion_source = directory / UPRIGHT_COPY
        except Exception as error:  # noqa: BLE001 - the page stays flagged and is converted as displayed
            for number, record in records.items():
                if record.get("state") == "sideways":
                    record["normalize_error"] = f"{type(error).__name__}: {str(error)[:120]}"
    for number in corrected:
        records[number].update(normalized=True, applied_rotate=records[number]["correction_rotate"])
    for page in analysis:
        record = records.get(page["page"])
        if record is not None:
            page["orientation"] = record
    return conversion_source


WORD = re.compile(r"[^\W_]+", re.UNICODE)
NUMBER = re.compile(r"(?<!\w)[+−-]?\d+(?:[.,:/]\d+)*(?!\w)")
CELL_TOKEN = re.compile(r"\w+|[^\w\s]")


def source_coverage(source: str, extracted: str) -> tuple[dict[str, int], Counter]:
    """Count matching occurrences and keep the exact grounded numeric occurrences."""
    source, extracted = (unicodedata.normalize("NFC", text).casefold().replace("−", "-") for text in (source, extracted))
    words = Counter(WORD.findall(source)) & Counter(WORD.findall(extracted))
    numbers = Counter(NUMBER.findall(source)) & Counter(NUMBER.findall(extracted))
    return {"words": sum(words.values()), "numbers": sum(numbers.values()), "unique_numbers": len(numbers)}, numbers


@dataclass
class RotationProbe:
    text: str
    tables: int = 0
    numeric_rows: Counter = field(default_factory=Counter)
    numeric_cell_anchors: tuple[frozenset, ...] = ()


def numeric_cell_anchors(table, words, height):
    """Identify original PDF words that agree with an entire numeric cell at its printed position."""
    anchors = set()
    for cell in table.data.table_cells:
        if cell.bbox is None or not NUMBER.search(cell.text):
            continue
        box = cell.bbox.to_top_left_origin(page_height=height)
        observed = [word for word in words if box.l <= (word[0] + word[2]) / 2 <= box.r
                    and box.t <= (word[1] + word[3]) / 2 <= box.b]
        text = unicodedata.normalize("NFC", " ".join(word[4] for word in observed))
        if CELL_TOKEN.findall(text) == CELL_TOKEN.findall(unicodedata.normalize("NFC", cell.text)):
            anchors.update(word[5:] for word in observed if NUMBER.search(word[4]))
    return frozenset(anchors)


def improved_table_geometry(original, upright):
    """Each original grid must have a distinct upright match with stronger source evidence."""
    if not original:
        return False
    assigned = set()
    for before in original:
        candidates = [i for i, after in enumerate(upright)
                      if len(before & after) > len(before - after) and len(after) > len(before)]
        if len(candidates) != 1 or candidates[0] in assigned:
            return False
        assigned.add(candidates[0])
    return True


def verify_working_copy(source: Path, upright: Path, analysis: list[dict],
                        read_converted: Callable[[Path, int], str | RotationProbe]) -> Path:
    """Require retained source content and preserved rows or stronger printed table geometry."""
    from .report_context import pdf_page_texts

    changed = {page["page"]: page["orientation"] for page in analysis if page.get("orientation", {}).get("normalized")}
    if not changed:
        return source
    accepted = {}
    for number, record in changed.items():
        try:
            text = pdf_page_texts(source, [number])[number]
            old = read_converted(source, number)
            new = read_converted(upright, number)
            old = RotationProbe(old) if isinstance(old, str) else old
            new = RotationProbe(new) if isinstance(new, str) else new
            before, before_numbers = source_coverage(text, old.text)
            after, after_numbers = source_coverage(text, new.text)
            numeric_losses = sum((before_numbers - after_numbers).values())
            row_losses = sum((old.numeric_rows - new.numeric_rows).values())
            source_ok = after["words"] > 0 and after["words"] >= before["words"] and not numeric_losses
            better_geometry = bool(row_losses) and improved_table_geometry(old.numeric_cell_anchors, new.numeric_cell_anchors)
            table_ok = new.tables >= old.tables and (not row_losses or better_geometry)
            decision = "normalized"
            if not source_ok:
                decision = "source_coverage_decreased"
            elif not table_ok:
                decision = "table_evidence_decreased"
            record["verification"] = {"original": before, "normalized": after,
                                      "lost_numeric_occurrences": numeric_losses,
                                      "original_tables": old.tables, "normalized_tables": new.tables,
                                      "lost_numeric_table_rows": row_losses,
                                      "original_anchored_numbers": sum(map(len, old.numeric_cell_anchors)),
                                      "normalized_anchored_numbers": sum(map(len, new.numeric_cell_anchors)),
                                      "improved_table_geometry": better_geometry, "decision": decision}
            if source_ok and table_ok:
                accepted[number] = record
        except (OSError, RuntimeError, ValueError) as error:
            record["verification"] = {"decision": "conversion_comparison_unavailable", "error": type(error).__name__}

    if accepted and accepted.keys() != changed.keys():
        try:
            normalize_working_copy(source, upright, accepted)
        except (OSError, RuntimeError, ValueError) as error:
            for record in accepted.values():
                record["verification"].update(decision="working_copy_unavailable", error=type(error).__name__)
            accepted.clear()
    for number in changed.keys() - accepted.keys():
        changed[number].pop("normalized", None)
        changed[number].pop("applied_rotate", None)
    return upright if accepted else source


def normalize_working_copy(source: Path, target: Path, records: dict[int, dict[str, Any]]) -> list[int]:
    """Write ``target`` = ``source`` with ``/Rotate`` set to ``correction_rotate`` for pages in state ``sideways``.
    Returns the corrected page numbers; no file is written when there are none. ``source`` is never modified."""
    import pypdfium2
    pages = sorted(number for number, record in records.items() if record.get("state") == "sideways")
    if not pages:
        return []
    with pypdfium2.PdfDocument(source) as pdf:
        for number in pages:
            page = pdf[number - 1]
            try:
                page.set_rotation(records[number]["correction_rotate"])
            finally:
                page.close()
        partial = target.with_name(target.name + ".partial")
        with open(partial, "wb") as stream:
            pdf.save(stream)
    partial.replace(target)
    return pages
