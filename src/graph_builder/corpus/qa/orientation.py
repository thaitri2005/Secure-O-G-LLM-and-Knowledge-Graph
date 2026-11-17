"""QA check (C-03, opt-in ``--orientation``): pages whose text was not upright when displayed (reason ``rotated_page``).

It reads only the ``orientation`` record that ``analysis.page_orientation`` stored with each page of the corpus work
folder; no PDF is opened. Without that option in the corpus configuration the work folder has no record and the check
emits nothing for a page (it does not claim the page is fine). The signals never claim that a structure is correct.
"""
from __future__ import annotations

from .signals import CheckContext, Registry

CHECK_NAME = "page_orientation"
CHECK_VERSION = "1"
LIMITATIONS = (
    "Needs corpus.analysis.page_orientation in the corpus configuration; work data without it gives no signal (NOT the same as upright).",
    "The direction is measured from the PDF text layer. Scanned or OCR pages have no usable layer: a rotated one is reported as orientation unknown, an unrotated one is not assessed, and a scan stored sideways without /Rotate is NOT detected.",
    "Text of several directions on one page (charts, stamps) is reported as mixed and is not corrected.",
    "A normalised page was converted from a working copy with /Rotate changed; this check does not show that its table structure now matches the page.",
)
REASONS = (
    ("ROTATED_PAGE_UNNORMALIZED", "WARN", "reason rotated_page: the text of this page is not upright when displayed and the page was converted as displayed; table and reading structure of the page are unverified.", CHECK_NAME),
    ("ROTATED_PAGE_NORMALIZED", "INFO", "reason rotated_page: this page was converted from a working copy whose /Rotate was changed so the text is upright; K1 page size and regions are in that upright frame; structure is not verified.", CHECK_NAME),
    ("ROTATED_PAGE_ORIENTATION_UNKNOWN", "WARN", "reason rotated_page: the page has /Rotate but no usable text layer (scan or OCR page); its displayed orientation could not be determined and was not corrected.", CHECK_NAME),
    ("ROTATED_PAGE_MIXED", "WARN", "reason rotated_page: the text of this page has no single dominant direction; it was not corrected and its structure is unverified.", CHECK_NAME),
    ("PAGE_ORIENTATION_FAILED", "WARN", "The orientation of this page could not be read (PARSING FAILURE, reason in evidence); nothing is known about it.", CHECK_NAME),
)
STATE_CODES = {"mixed": "ROTATED_PAGE_MIXED", "no_text_rotated": "ROTATED_PAGE_ORIENTATION_UNKNOWN", "failed": "PAGE_ORIENTATION_FAILED"}


def check_orientation(registry: Registry):
    def check(context: CheckContext, entity: dict) -> list[dict]:
        record = entity.get("orientation")
        if not record:
            return []
        state = record.get("state")
        if state == "sideways":
            code = "ROTATED_PAGE_NORMALIZED" if record.get("normalized") else "ROTATED_PAGE_UNNORMALIZED"
        else:
            code = STATE_CODES.get(state)
        if code is None:
            return []
        evidence = {key: record[key] for key in ("state", "status", "reason", "rotation", "text_direction", "displayed", "applied_rotate",
                                                 "dominant_share", "steps", "detail", "normalize_error") if key in record}
        return [registry.signal(code, "page", entity["ids"], evidence=evidence)]
    return check


def register_orientation(registry: Registry) -> Registry:
    for code, severity, meaning, emitter in REASONS:
        registry.register_reason(code, severity, meaning, emitter)
    registry.register_check(CHECK_NAME, check_orientation(registry), "page", CHECK_VERSION, limitations=LIMITATIONS)
    return registry
