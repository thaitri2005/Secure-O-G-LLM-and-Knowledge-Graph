"""Resolve the report date and well of every page of a daily report, and the one well of a single-well document."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any, Iterable

DATE_KEYS = ("Report For",)
WELL_KEYS = ("Well ID:", "Well Name:")
HEADER_END = re.compile(r"^(?:ops summary|planned ops|present operations|activity planned|daily op|forecast op|casing data|time breakdown|operations summary|from\s+to)\b", re.I)


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


def pdf_page_texts(pdf_path: Path, pages: Iterable[int], *, source_texts: dict[int, str] | None = None) -> dict[int, str]:
    if source_texts is not None:
        return {number: source_texts[number] for number in pages}
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


def document_well(page_texts: dict[int, str], config: dict[str, Any]) -> tuple[str, list[str]]:
    """Return (well, candidates) for a document about one well, such as an end-of-well report.

    ``config`` is the optional ``document_context`` section of the K1 configuration. Every match of every
    ``well_patterns`` entry on the first ``pages`` pages is a candidate. The well is set only when exactly one
    distinct candidate is found; none or several give an empty well, so a body page naming another well (TG-2 in
    AK-3's report) can never decide it.
    """
    candidates: list[str] = []
    for number in sorted(page_texts)[:config["pages"]]:
        text = page_texts[number].replace("\r\n", "\n").replace("\r", "\n")
        for pattern in config["well_patterns"]:
            candidates.extend(match.group(1) for match in re.finditer(pattern, text))
    distinct = sorted(set(candidates))
    return (distinct[0] if len(distinct) == 1 else ""), distinct


def document_contexts(pdf_path: Path, pages: Iterable[int], document_type: str,
                      config: dict[str, Any] | None) -> tuple[dict[int, dict], list[int], dict | None]:
    """The ``{"well"}`` context of every page of a document type named in ``document_context``.

    Returns the contexts by page, the pages left without one (all pages when the well does not resolve) and a
    finding with the candidates, or ``({}, [], None)`` when the option is absent or does not cover the type."""
    if not config or document_type not in config["document_types"]:
        return {}, [], None
    pages = list(pages)
    well, candidates = document_well(pdf_page_texts(pdf_path, pages[:config["pages"]]), config)
    finding = {"well": well, "candidates": candidates}
    if not well:
        return {}, pages, finding
    return {number: {"well": well} for number in pages}, [], finding


def report_contexts(pdf_path: Path, pages: Iterable[int], forms: dict[int, dict], document_type: str,
                    config: dict[str, Any], *, source_texts: dict[int, str] | None = None
                    ) -> tuple[dict[int, dict], list[dict], list[int]]:
    """Resolve the context of each 1-based page of a daily report.

    ``forms`` maps page numbers to the form extracted on that page, ``config`` is the ``report_context`` section
    of the K1 configuration. Returns the contexts by page (only pages that resolved), the conflicts between form
    and text, and the pages without a context. Documents of other types return no contexts and no missing pages.
    """
    if document_type not in config["document_types"]:
        return {}, [], []
    pages = list(pages)
    contexts, conflicts, missing = {}, [], []
    for number, text in pdf_page_texts(pdf_path, pages, source_texts=source_texts).items():
        form = forms.get(number)
        context = page_context(form, text, config)
        if context:
            contexts[number] = context
        else:
            missing.append(number)
        conflicts.extend({"page": number, **conflict} for conflict in page_conflicts(form, text, config))
    return contexts, conflicts, missing


def physical_context_fields(layer: dict) -> dict[str, str]:
    """Read explicit identity pairs from visible header rows, before any body or table."""
    from .report_fields import DATE, HEADER_RULES, field_candidates, normalized, supported
    from .table_recognition import page_lines

    rows = []
    for row in page_lines(layer):
        text = " ".join(word["text"] for word in row["words"])
        if row["bottom"] > layer["height"] / 3 or HEADER_END.search(text):
            break
        rows.append((row, text))
    rules = {name: HEADER_RULES[name] for name in ("well", "report", "report_for", "spud", "permit")}
    rules["date"] = re.compile(fr"(?<!\w)(?<!spud\s)(?P<key>(?:(?:report|rpt)\s+)?date\s*:?)\s+(?P<value>{DATE})(?=\s|$)", re.I)
    candidates = list(field_candidates(layer, rows, rules))
    peers = [field for _, field in candidates]
    accepted: dict[str, set[str]] = {}
    for kind, field in candidates:
        if not supported(field, peers):
            continue
        value = field["value"]
        if kind == "report":
            _, _, value = value.partition(" ")
        if kind == "well" and normalized(field["key"]).rstrip(":") == "well id":
            kind = "well_id"
        if value:
            accepted.setdefault(kind, set()).add(value)
    result = {kind: next(iter(values)) for kind, values in accepted.items() if len(values) == 1}
    if not accepted.get("well") and "well_id" in result:
        result["well"] = result["well_id"]
    return result


def slash_order(value: str) -> str | None:
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/\d{2,4}", value)
    if match:
        first, second = map(int, match.groups())
        if first > 12 >= second:
            return "day"
        if second > 12 >= first:
            return "month"
    return None


def canonical_date(value: str, slash: str | None) -> str | None:
    formats = ["%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y"]
    order = slash_order(value) or slash
    if order == "day" or (not order and re.match(r"^(\d{1,2})/\1/", value)):
        formats += ["%d/%m/%Y", "%d/%m/%y"]
    if order == "month":
        formats += ["%m/%d/%Y", "%m/%d/%y"]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def report_context_fallback(pdf: Path, pages: list[dict], missing: list[int], stacked_pages=()) -> dict[int, dict]:
    """Resolve the report day and well on missing text pages without borrowing another page's identity."""
    from .orientation import normalized_rotation
    from .text_layer import source_page

    unresolved = set(missing) - set(stacked_pages)
    fields = {}
    for entry in pages:
        number = entry["page"]
        if number not in unresolved or entry["mode"] != "text":
            continue
        rotation = normalized_rotation(entry)
        try:
            layer = source_page(pdf, number, displayed_origin=True, rotation_override=rotation[1] if rotation else None)
        except (OSError, ValueError, RuntimeError):
            continue
        if not layer["rotation"] or rotation:
            fields[number] = physical_context_fields(layer)
    orders: dict[str, set[str]] = {}
    for values in fields.values():
        if well := values.get("well"):
            for key in ("report_for", "report", "date", "spud"):
                if order := slash_order(values.get(key, "")):
                    orders.setdefault(well.casefold(), set()).add(order)
    resolved = {}
    for number, values in fields.items():
        well = values.get("well")
        raw_date = next((values[key] for key in ("report_for", "report", "date") if key in values), "")
        if well and raw_date:
            choices = orders.get(well.casefold(), set())
            date = canonical_date(raw_date, next(iter(choices)) if len(choices) == 1 else None)
            if date:
                resolved[number] = {"well": well, "report_date": date}
    return resolved
