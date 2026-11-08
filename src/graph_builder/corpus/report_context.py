"""Resolve the report date and well of every page of a daily report."""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Iterable

DATE_KEYS = ("Report For",)
WELL_KEYS = ("Well ID:", "Well Name:")


def first_match(patterns: list[str], text: str) -> str:
    for pattern in patterns:
        found = re.search(pattern, text)
        if found:
            return found.group(1)
    return ""


def form_values(form: dict | None) -> tuple[str, str]:
    """Return (date, well) from a verified template form, or empty strings."""
    if not form or not form.get("verified"):
        return "", ""
    values = {field["key"]: field["value"] for field in form["fields"]}
    return (next((values[key] for key in DATE_KEYS if values.get(key)), ""),
            next((values[key] for key in WELL_KEYS if values.get(key)), ""))


def text_values(page_text: str, config: dict[str, Any]) -> tuple[str, str]:
    """Return (date, well) found by the configured regular expressions in the page text."""
    return first_match(config["date_patterns"], page_text), first_match(config["well_patterns"], page_text)


def page_context(form: dict | None, page_text: str, config: dict[str, Any]) -> dict:
    """Return {"report_date", "well"} when both resolve; verified form fields win over the text patterns."""
    form_date, form_well = form_values(form)
    text_date, text_well = text_values(page_text, config)
    date, well = form_date or text_date, form_well or text_well
    return {"report_date": date, "well": well} if date and well else {}


def page_conflicts(form: dict | None, page_text: str, config: dict[str, Any]) -> list[dict]:
    """List fields where a verified form and the text patterns both resolve but disagree."""
    form_date, form_well = form_values(form)
    text_date, text_well = text_values(page_text, config)
    return [{"field": name, "form": from_form, "text": from_text}
            for name, from_form, from_text in (("report_date", form_date, text_date), ("well", form_well, text_well))
            if from_form and from_text and from_form != from_text]


def pdf_page_texts(pdf_path: Path, pages: Iterable[int]) -> dict[int, str]:
    import pypdfium2 as pdfium
    texts = {}
    with pdfium.PdfDocument(pdf_path) as pdf:
        for number in pages:
            page = pdf[number - 1]
            textpage = page.get_textpage()
            texts[number] = textpage.get_text_range()
            textpage.close()
            page.close()
    return texts


def report_contexts(pdf_path: Path, pages: Iterable[int], forms: dict[int, dict], document_type: str,
                    config: dict[str, Any]) -> tuple[dict[int, dict], list[dict], list[int]]:
    """Resolve the context of each 1-based page of a daily report.

    ``forms`` maps page numbers to the form extracted on that page, ``config`` is the ``report_context`` section
    of the K1 configuration. Returns the contexts by page (only pages that resolved), the conflicts between form
    and text, and the pages without a context. Documents of other types return no contexts and no missing pages.
    """
    if document_type not in config["document_types"]:
        return {}, [], []
    pages = list(pages)
    contexts, conflicts, missing = {}, [], []
    for number, text in pdf_page_texts(pdf_path, pages).items():
        form = forms.get(number)
        context = page_context(form, text, config)
        if context:
            contexts[number] = context
        else:
            missing.append(number)
        conflicts.extend({"page": number, **conflict} for conflict in page_conflicts(form, text, config))
    return contexts, conflicts, missing
