"""Source annotations "N records not printed" (A-414).

Problem: some PDF reports print a note beside a table title saying that records were left out of the print
("3 records not printed", "(1 not shown)"). K1 keeps the table that was printed; the note says that the table is a
partial view of the underlying data. Without a signal a consumer cannot tell.

What this check does: it reads the text layer of the source PDF (same pdfium source as the fidelity check), finds short
text segments that match the configured patterns, finds the nearest table title on the same line to name the table family,
and matches the note to the release table that starts below it (or contains it). It emits ``ANNOTATION_RECORDS_NOT_PRINTED``
(INFO) at table scope when a table matched and at page scope otherwise. The ledger then sets ``completeness`` of that scope to
PARTIAL_IN_SOURCE. No signal means only "no such note was found by these patterns".

What it does not do: it does not check the count N against anything, does not detect notes without a number, in other
languages, inside images, or on rotated pages (those fall back to page text lines without position), and a note that
matches no configured pattern is invisible. See LIMITATIONS.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from statistics import median
from typing import Any

from .fidelity import FidelityState, iter_jsonl
from .signals import CheckContext, Registry

CHECK_NAME = "annotations"
CHECK_VERSION = "1"
CODE = "ANNOTATION_RECORDS_NOT_PRINTED"
DEFAULT_CONFIG = Path(__file__).resolve().parents[4] / "configs" / "qa" / "annotations.json"

REASONS = (
    (CODE, "INFO", "The source PDF states that records were not printed or shown beside a table title; the table or page is partial in the source (the count is the note's own claim, not checked).", CHECK_NAME),
)
LIMITATIONS = (
    "Finds only the configured wordings with a number; a note without a number, in another language, in an image or in a scanned page is not detected.",
    "The count N is copied from the note and is never compared with the table.",
    "Table matching is geometric (the table starts below the note or contains it); a wrong table can match when two tables are close, and a table that K1 did not extract cannot match (the note stays at page scope).",
    "Rotated pages are searched in page text lines without position, so they cannot be matched to a table.",
    "Patterns come from two report templates of 94 public PDFs; other templates are NOT EVALUATED.",
)


def load_config(path: Path | None = None) -> dict:
    return json.loads((path or DEFAULT_CONFIG).read_text(encoding="utf-8"))


def _value(config: dict, name: str) -> Any:
    return config["geometry"][name]["value"]


def compiled_patterns(config: dict) -> list[tuple[str, re.Pattern]]:
    return [(item["name"], re.compile(item["regex"], re.IGNORECASE)) for item in config["patterns"]]


def _union(boxes: list[list[float]]) -> list[float]:
    return [round(min(b[0] for b in boxes), 2), round(min(b[1] for b in boxes), 2),
            round(max(b[2] for b in boxes), 2), round(max(b[3] for b in boxes), 2)]


def build_segments(words: list[dict], config: dict) -> list[dict]:
    """Group layer words into lines (vertical centres within a fraction of the word height), then split each line at wide
    horizontal gaps. Returns [{text, bbox}] in reading order. Pure and deterministic."""
    usable = [w for w in words if str(w.get("text", "")).strip() and w.get("bbox")]
    if not usable:
        return []
    height = median(max(w["bbox"][3] - w["bbox"][1], 0.1) for w in usable)
    tolerance, gap_limit = _value(config, "line_tolerance_ratio") * height, _value(config, "segment_gap_em")
    ordered = sorted(usable, key=lambda w: ((w["bbox"][1] + w["bbox"][3]) / 2, w["bbox"][0], w["text"]))
    lines: list[list[dict]] = []
    centres: list[float] = []
    for word in ordered:
        centre = (word["bbox"][1] + word["bbox"][3]) / 2
        if lines and abs(centre - centres[-1]) <= tolerance:
            lines[-1].append(word)
            centres[-1] = sum((w["bbox"][1] + w["bbox"][3]) / 2 for w in lines[-1]) / len(lines[-1])
        else:
            lines.append([word])
            centres.append(centre)
    segments = []
    for line in lines:
        line.sort(key=lambda w: (w["bbox"][0], w["text"]))
        group = [line[0]]
        for word in line[1:]:
            previous = group[-1]["bbox"]
            em = max(word["bbox"][3] - word["bbox"][1], previous[3] - previous[1], 0.1)
            if word["bbox"][0] - previous[2] > gap_limit * em:
                segments.append(group)
                group = []
            group.append(word)
        segments.append(group)
    return [{"text": " ".join(w["text"] for w in group), "bbox": _union([w["bbox"] for w in group])} for group in segments]


def segments_from_text(text: str) -> list[dict]:
    """Fallback without geometry (rotated pages): one segment per non-empty text line."""
    return [{"text": " ".join(line.split()), "bbox": None} for line in text.splitlines() if line.strip()]


def _family_of(text: str, config: dict) -> str | None:
    for item in config["families"]:
        if re.search(item["title_regex"], text, re.IGNORECASE):
            return item["family"]
    return None


def _count(raw: str) -> int | None:
    digits = raw.replace(",", "")
    return int(digits) if digits.isdigit() else None


def find_annotations(segments: list[dict], config: dict) -> list[dict]:
    """Annotation hits: a segment containing a configured pattern with at most ``max_context_words`` other words.
    Hit: {pattern, count, text, context, bbox, family_in_segment}. Longer segments are prose and are ignored."""
    limit = _value(config, "max_context_words")
    hits = []
    for segment in segments:
        for name, regex in compiled_patterns(config):
            match = regex.search(segment["text"])
            if not match:
                continue
            count = _count(match.group("n"))
            context = (segment["text"][:match.start()] + " " + segment["text"][match.end():]).split()
            if count is None or len(context) > limit:
                continue
            hits.append({"pattern": name, "count": count, "text": match.group(0), "context": " ".join(context),
                         "bbox": segment["bbox"], "family_in_segment": _family_of(" ".join(context), config)})
            break
    return hits


def nearest_title(hit: dict, segments: list[dict], config: dict) -> dict | None:
    """Family and text of the title belonging to the note: the context of the same segment, a title segment on the same line,
    or the closest title segment above within ``title_max_gap_pt``. {family, text, relation} or None."""
    if hit["family_in_segment"]:
        return {"family": hit["family_in_segment"], "text": hit["context"], "relation": "same_segment"}
    box = hit["bbox"]
    if box is None:
        return None
    overlap_min, max_gap = _value(config, "title_line_overlap"), _value(config, "title_max_gap_pt")
    best = None
    for segment in segments:
        other = segment["bbox"]
        family = _family_of(segment["text"], config)
        if other is None or family is None or len(segment["text"].split()) > _value(config, "max_context_words"):
            continue
        shared = min(box[3], other[3]) - max(box[1], other[1])
        if shared >= overlap_min * max(box[3] - box[1], 0.1):
            key, relation = (0.0, other[0]), "same_line"
        elif 0 < box[1] - other[3] <= max_gap:
            key, relation = (box[1] - other[3], other[0]), "above"
        else:
            continue
        if best is None or key < best[0]:
            best = (key, {"family": family, "text": segment["text"], "relation": relation})
    return best[1] if best else None


def match_table(hit: dict, parts: list[dict], config: dict) -> dict | None:
    """Release table whose part contains the note or starts within ``table_max_gap_pt`` below it, with horizontal overlap.
    ``parts``: [{table_id, bbox}] of the same page. Returns {table_id, kind, gap_pt} or None. The nearest part wins."""
    box = hit["bbox"]
    if box is None:
        return None
    slack, max_gap = _value(config, "table_slack_pt"), _value(config, "table_max_gap_pt")
    best = None
    for part in parts:
        b = part["bbox"]
        if min(box[2], b[2] + slack) - max(box[0], b[0] - slack) <= 0:
            continue
        centre = (box[1] + box[3]) / 2
        if b[1] - slack <= centre <= b[3] + slack:
            candidate = (0.0, part["table_id"], "inside")
        elif -slack <= b[1] - box[3] <= max_gap:
            candidate = (round(max(0.0, b[1] - box[3]), 2), part["table_id"], "below")
        else:
            continue
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    return {"table_id": best[1], "kind": best[2], "gap_pt": best[0]} if best else None


def analyse_page(segments: list[dict], parts: list[dict], config: dict) -> list[dict]:
    """All annotation hits of one page with family, title and table match. Pure; ``parts`` are the release table parts of the page."""
    out = []
    for hit in sorted(find_annotations(segments, config), key=lambda h: (h["bbox"] or [0, 0, 0, 0], h["text"])):
        title = nearest_title(hit, segments, config)
        match = match_table(hit, parts, config)
        out.append({"pattern": hit["pattern"], "count": hit["count"], "text": hit["text"], "bbox": hit["bbox"],
                    "family": title["family"] if title else config["unknown_family"],
                    "title": title, "table": match})
    return out


def candidate_pages(pdf_path: Path, config: dict) -> list[tuple[int, str]]:
    """(page number, page text) of pages whose plain text mentions a configured phrase; opens the PDF once."""
    import pypdfium2 as pdfium
    patterns = compiled_patterns(config)
    out = []
    with pdfium.PdfDocument(pdf_path) as pdf:
        for index in range(len(pdf)):
            textpage = pdf[index].get_textpage()
            text = textpage.get_text_range()
            textpage.close()
            if any(regex.search(text) for _, regex in patterns):
                out.append((index + 1, text))
    return out


def scan_pdf(pdf_path: Path, config: dict, parts_by_page: dict[int, list[dict]] | None = None) -> dict:
    """Annotation hits of one PDF: {"pages": {page: [hit...]}, "rotated_pages": [...], "errors": [...]}. Per-page isolation."""
    from graph_builder.corpus.text_layer import source_page
    result: dict[str, Any] = {"pages": {}, "rotated_pages": [], "errors": []}
    for page, text in candidate_pages(pdf_path, config):
        try:
            layer = source_page(pdf_path, page)
            if layer["rotation"] != 0:
                result["rotated_pages"].append(page)
                segments = segments_from_text(text)
            else:
                segments = build_segments(layer["words"], config)
            hits = analyse_page(segments, (parts_by_page or {}).get(page, []), config)
        except Exception as error:  # noqa: BLE001 - per-page isolation: an unreadable page is recorded, the scan continues
            result["errors"].append({"page": page, "error": type(error).__name__})
            continue
        if hits:
            result["pages"][page] = hits
    return result


def release_parts(release_dir: Path) -> dict[str, dict[int, list[dict]]]:
    """file_id -> page -> [{table_id, bbox}] for every table part of the release. Streams tables.jsonl."""
    out: dict[str, dict[int, list[dict]]] = {}
    for table in iter_jsonl(release_dir / "tables.jsonl"):
        for part in table.get("parts", []):
            if part.get("bbox") and part.get("page") is not None:
                out.setdefault(table["file_id"], {}).setdefault(part["page"], []).append(
                    {"table_id": table["table_id"], "bbox": part["bbox"]})
    return out


def scan_release(release_dir: Path, corpus_dir: Path | None, config: dict) -> dict:
    """{"tables": table_id -> [hit], "pages": (file_id, page) -> [hit not matched to a table], "reasons": file_id -> reason}."""
    state = FidelityState(release_dir, corpus_dir, config)
    parts = release_parts(release_dir)
    tables: dict[str, list[dict]] = {}
    pages: dict[tuple[str, int], list[dict]] = {}
    reasons: dict[str, str] = {}
    for file_id in sorted(state.files):
        path, reason = state.locate_pdf(state.files[file_id])
        if path is None:
            reasons[file_id] = reason
            continue
        try:
            scanned = scan_pdf(path, config, parts.get(file_id))
        except Exception as error:  # noqa: BLE001 - per-document isolation
            reasons[file_id] = f"PDF unreadable: {type(error).__name__}"
            continue
        for page, hits in scanned["pages"].items():
            for hit in hits:
                if hit["table"]:
                    tables.setdefault(hit["table"]["table_id"], []).append({**hit, "page": page})
                else:
                    pages.setdefault((file_id, page), []).append({**hit, "page": page})
    return {"tables": tables, "pages": pages, "reasons": reasons}


def _evidence(hit: dict) -> dict:
    return {"count": hit["count"], "text": hit["text"], "pattern": hit["pattern"], "family": hit["family"],
            "title": (hit["title"] or {}).get("text"), "title_relation": (hit["title"] or {}).get("relation"),
            "position": {"page": hit["page"], "bbox": hit["bbox"]},
            "table_id": (hit["table"] or {}).get("table_id"), "table_match": hit["table"],
            "source": "pdf_text_layer", "count_checked_against_table": False}


def register_annotations(registry: Registry, corpus_dir: Path | None = None, config_path: Path | None = None) -> Registry:
    """Add a table-scope and a page-scope check. The release scan runs lazily once per release."""
    config = load_config(config_path)
    holder: dict[str, Any] = {}
    for code, severity, meaning, emitter in REASONS:
        registry.register_reason(code, severity, meaning, emitter)

    def scan(context: CheckContext) -> dict:
        key = str(context.release_dir)
        if holder.get("key") != key:
            holder.update(key=key, scan=scan_release(Path(context.release_dir), corpus_dir, config))
        return holder["scan"]

    def table_check(context: CheckContext, entity: dict) -> list[dict]:
        hits = scan(context)["tables"].get(entity["ids"].get("table_id"), [])
        return [registry.signal(CODE, "table", entity["ids"], evidence=_evidence(hit)) for hit in hits]

    def page_check(context: CheckContext, entity: dict) -> list[dict]:
        hits = scan(context)["pages"].get((entity["ids"].get("file_id"), entity["ids"].get("page")), [])
        return [registry.signal(CODE, "page", entity["ids"], evidence=_evidence(hit)) for hit in hits]

    registry.register_check(CHECK_NAME + "_table", table_check, "table", CHECK_VERSION, limitations=LIMITATIONS)
    registry.register_check(CHECK_NAME + "_page", page_check, "page", CHECK_VERSION, limitations=LIMITATIONS)
    return registry
