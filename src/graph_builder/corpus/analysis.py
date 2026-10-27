"""Inspect each PDF page's text layer and images, and decide how the page must be read.

Modes:
- ``text``: the embedded text layer is complete and well formed; no OCR.
- ``hybrid``: good text layer plus substantial images; OCR only regions the text layer does not cover.
- ``ocr``: no usable text layer (scan, outlined glyphs, garbled or legacy-encoded fonts, poor hidden OCR layer);
  OCR the whole page and ignore the text layer.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import unicodedata

from .vietnamese import text_profile

DEFAULT_ANALYSIS = {
    "min_text_chars": 30,            # fewer non-space characters means the page has no real text layer
    "scan_image_coverage": 0.05,     # ...and an image this large (share of page area) means it is a scan
    "vector_text_paths": 400,        # ...or this many path objects means text drawn as outlines
    "hybrid_image_coverage": 0.15,   # good text plus images this large: OCR the image regions too
    "bad_char_rate": 0.02,           # replacement, private-use and control characters
    "foreign_letter_rate": 0.08,     # words with letters neither basic Latin nor Vietnamese uses
    "invalid_vietnamese_rate": 0.2,  # Vietnamese-marked words that are not well-formed syllables
    "min_profile_words": 15,         # spelling rates are judged only on pages with at least this many words
    "hidden_text_ratio": 0.5,        # share of invisible text objects marking a scanner's OCR layer
}


@dataclass
class PageAnalysis:
    page: int
    width: float
    height: float
    rotation: int
    text_chars: int
    image_coverage: float
    path_objects: int
    text_objects: int
    invisible_text_objects: int
    bad_char_rate: float
    profile: dict[str, Any] = field(default_factory=dict)
    mode: str = "text"
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def analysis_config(supplied: dict[str, Any] | None) -> dict[str, Any]:
    supplied = supplied or {}
    if not isinstance(supplied, dict) or set(supplied) - DEFAULT_ANALYSIS.keys():
        raise ValueError(f"analysis accepts only {sorted(DEFAULT_ANALYSIS)}")
    settings = {**DEFAULT_ANALYSIS, **supplied}
    for key, value in settings.items():
        if type(value) not in (int, float) or value < 0:
            raise ValueError(f"analysis.{key} must be a nonnegative number")
    return settings


def union_area(boxes: list[tuple[float, float, float, float]]) -> float:
    """Area covered by axis-aligned boxes (left, bottom, right, top), counting overlaps once."""
    edges = sorted({x for left, _, right, _ in boxes for x in (left, right)})
    area = 0.0
    for left, right in zip(edges, edges[1:]):
        spans = sorted((bottom, top) for l, bottom, r, top in boxes if l <= left and right <= r)
        reach = float("-inf")
        for bottom, top in spans:
            area += (right - left) * max(0.0, top - max(bottom, reach))
            reach = max(reach, top)
    return area


def bad_characters(text: str) -> int:
    count = 0
    for char in text:
        if char == "�" or "" <= char <= "":
            count += 1
        elif unicodedata.category(char) == "Cc" and char not in "\r\n\t":
            count += 1
    return count


def decide(page: PageAnalysis, settings: dict[str, Any]) -> PageAnalysis:
    words = page.profile.get("words", 0)
    if page.text_chars < settings["min_text_chars"]:
        if page.image_coverage >= settings["scan_image_coverage"]:
            page.mode, page.reasons = "ocr", ["no_text_layer_image"]
        elif page.path_objects >= settings["vector_text_paths"]:
            page.mode, page.reasons = "ocr", ["no_text_layer_vector_paths"]
        else:
            page.mode, page.reasons = "text", ["blank_or_sparse"]
        return page
    reasons = []
    if page.bad_char_rate > settings["bad_char_rate"]:
        reasons.append("bad_characters")
    if words >= settings["min_profile_words"]:
        if page.profile["foreign_letter_rate"] > settings["foreign_letter_rate"]:
            reasons.append("foreign_letters")
        if (page.profile["vietnamese_words"] >= settings["min_profile_words"]
                and page.profile["invalid_vietnamese_rate"] > settings["invalid_vietnamese_rate"]):
            reasons.append("invalid_vietnamese")
    hidden = page.text_objects and page.invisible_text_objects / page.text_objects >= settings["hidden_text_ratio"]
    if reasons:
        page.mode, page.reasons = "ocr", (["hidden_text_layer"] if hidden else []) + reasons
    elif page.image_coverage >= settings["hybrid_image_coverage"]:
        page.mode, page.reasons = "hybrid", ["hidden_text_layer" if hidden else "images_with_text"]
    else:
        page.mode, page.reasons = "text", ["text_layer_ok"]
    return page


def analyze_pdf(path: Path, settings: dict[str, Any]) -> list[PageAnalysis]:
    """Analyze every page with pdfium; nothing is rendered."""
    import pypdfium2
    import pypdfium2.raw as raw

    pages = []
    with pypdfium2.PdfDocument(path) as pdf:
        for index in range(len(pdf)):
            page = pdf[index]
            try:
                width, height = page.get_size()
                textpage = page.get_textpage()
                text = textpage.get_text_range()
                textpage.close()
                images, paths, texts, invisible = [], 0, 0, 0
                for obj in page.get_objects(max_depth=3):
                    if obj.type == raw.FPDF_PAGEOBJ_IMAGE:
                        left, bottom, right, top = obj.get_bounds()
                        images.append((max(0.0, left), max(0.0, bottom), min(width, right), min(height, top)))
                    elif obj.type == raw.FPDF_PAGEOBJ_PATH:
                        paths += 1
                    elif obj.type == raw.FPDF_PAGEOBJ_TEXT:
                        texts += 1
                        if raw.FPDFTextObj_GetTextRenderMode(obj.raw) == raw.FPDF_TEXTRENDERMODE_INVISIBLE:
                            invisible += 1
                visible = [box for box in images if box[2] > box[0] and box[3] > box[1]]
                stripped = "".join(text.split())
                result = PageAnalysis(page=index + 1, width=round(width, 2), height=round(height, 2),
                                      rotation=int(page.get_rotation()), text_chars=len(stripped),
                                      image_coverage=round(min(1.0, union_area(visible) / (width * height)), 4) if width * height else 0.0,
                                      path_objects=paths, text_objects=texts, invisible_text_objects=invisible,
                                      bad_char_rate=round(bad_characters(stripped) / len(stripped), 4) if stripped else 0.0,
                                      profile=text_profile(text))
                pages.append(decide(result, settings))
            finally:
                page.close()
    return pages


def segments(modes: list[str], max_pages: int) -> list[tuple[str, int, int]]:
    """Group pages into conversion segments (mode, first, last), 1-based and inclusive.

    OCR pages are converted one page at a time so that a page can be re-read with another engine;
    text and hybrid pages are batched up to ``max_pages``.
    """
    result: list[tuple[str, int, int]] = []
    for number, mode in enumerate(modes, 1):
        if (result and result[-1][0] == mode and mode != "ocr"
                and result[-1][2] == number - 1 and number - result[-1][1] < max_pages):
            result[-1] = (mode, result[-1][1], number)
        else:
            result.append((mode, number, number))
    return result
