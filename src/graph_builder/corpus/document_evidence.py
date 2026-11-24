"""Recognize a document type from visible report headings on its source pages."""
from __future__ import annotations

import re
from pathlib import Path

from .report_fields import DAILY_TITLE, HEADER_RULES

DAILY_HEADING = DAILY_TITLE.pattern.removeprefix(r"\b").removesuffix(r"\b") + "s?"
HEADINGS = {
    "daily_report": DAILY_HEADING,
    "eowr": r"(?:end[ -]of[ -]well|(?:final )?well completion) reports?(?: (?:of|for) .+)?",
    "casing_report": r"casing (?:data|information|record) report",
    "survey_report": r"(?:directional|wellbore) survey report",
    "drilling_plan": r"(?:well )?drilling (?:plan|program(?:me)?)",
    "permit": r"(?:well drilling permit|permit (?:to drill|for drilling))",
}
HEADINGS = {kind: re.compile(r"(?:\d+[a-z.]?\. )?" + pattern, re.I) for kind, pattern in HEADINGS.items()}
SUMMARY = re.compile(r"summary repor\s*t", re.I)
NAMED_DAILY = re.compile(r".+ " + DAILY_HEADING, re.I)


def source_document_type(pdf: Path, pages: list[dict], default: str, *,
                         missing_title_type: str | None = None) -> tuple[str, str]:
    """Use the first unambiguous heading in a visible text header, including in appendices.

    A conflicting header keeps the default. An ID-based type is allowed only when no heading is recognized.
    Table and form readers have their own evidence and are independent of this label.
    """
    import pymupdf

    missing_title = (missing_title_type, "doc_id") if missing_title_type is not None else (default, "default")
    text_pages = [page for page in pages if page["mode"] in {"text", "hybrid"}
                  and not (page.get("orientation") or {}).get("normalized")]
    if not text_pages:
        return missing_title
    flags = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
    with pymupdf.open(pdf) as source:
        for record in text_pages:
            page = source[record["page"] - 1]
            if page.rotation:
                continue
            clip = (0, 0, page.rect.width, page.rect.height / 3)
            lines = [" ".join("".join(span["text"] for span in line["spans"]).split())
                     for block in page.get_text("dict", clip=clip, flags=flags)["blocks"]
                     for line in block.get("lines", ())]
            types = {kind for kind, pattern in HEADINGS.items() if any(pattern.fullmatch(line) for line in lines)}
            named_daily = any(NAMED_DAILY.fullmatch(line) for line in lines)
            summary = any(SUMMARY.fullmatch(line) for line in lines)
            if named_daily or summary:
                # A title with extra text needs corroboration from the typed identity in the header.
                header = page.get_text("text", clip=clip, sort=True).splitlines()
                identity = {key for key in ("well", "period", "report", "date", "report_for")
                            if any(HEADER_RULES[key].search(line.lstrip()) for line in header)}
                if {"well", "report"} <= identity and ("period" in identity
                        or named_daily and identity & {"date", "report_for"}):
                    types.add("daily_report")
            if len(types) == 1:
                return next(iter(types)), "pdf_title"
            if types:
                return default, "default"
    return missing_title
