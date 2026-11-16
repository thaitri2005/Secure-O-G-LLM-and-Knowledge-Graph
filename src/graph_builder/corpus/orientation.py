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
import math
from pathlib import Path
from typing import Any

MODES = ("flag", "normalize")
DEFAULT_SETTINGS = {
    "min_chars": 40,           # fewer measured glyph steps: the direction is not judged
    "dominant_share": 0.8,     # share of glyph steps that must point the same way
    "angle_tolerance": 10.0,   # degrees; steps further from a multiple of 90 count as oblique
    "max_steps": 4000,         # glyph steps measured per page (evenly strided, deterministic)
}
REASON = "rotated_page"


def orientation_settings(supplied: Any) -> dict[str, Any]:
    """Validate ``analysis.page_orientation``: ``{"mode": "flag"|"normalize", ...thresholds}``."""
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


def apply_page_orientation(source: Path, directory: Path, analysis: list[dict[str, Any]], settings: dict[str, Any]) -> Path:
    """Attach ``orientation`` to every page dict of ``analysis`` and return the file Docling must convert.

    ``flag`` returns ``source``. ``normalize`` returns ``directory / UPRIGHT_COPY`` when at least one page was corrected,
    else ``source``. A failed copy keeps ``source`` and marks the pages ``normalize_error`` (the page stays flagged)."""
    records = analyze_orientation(source, settings, {page["page"] for page in analysis if page.get("mode") == "ocr"})
    conversion_source, corrected = source, []
    if settings["mode"] == "normalize":
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
