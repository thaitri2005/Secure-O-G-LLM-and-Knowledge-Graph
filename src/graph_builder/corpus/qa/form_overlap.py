"""Compare complete form and text pairs, and project a retrieval view of a K1 release."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
import unicodedata

from ..k1_build import form_text
from ..store import atomic_write_jsonl, read_jsonl
from .signals import CheckContext, Registry

CHECK = "form_text_overlap"
DUPLICATE = "FORM_TEXT_DUPLICATE"
CONFLICT = "FORM_TEXT_SOURCE_CONFLICT"
GEOMETRY_TOLERANCE_PT = 2
VIEW_KEYS = ("chunk_id", "file_id", "doc_id", "page", "pages", "type", "section",
             "table_id", "form_id", "row_start", "row_end", "context")


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def label_key(text: str) -> str:
    return normalize(text).rstrip(":").rstrip().casefold()


def valid_box(box: list | None) -> bool:
    return bool(box and len(box) == 4 and all(isfinite(x) for x in box)
                and box[0] < box[2] and box[1] < box[3])


def covers(region: list, box: list) -> bool:
    pad = GEOMETRY_TOLERANCE_PT
    return (region[0] - pad <= box[0] and region[1] - pad <= box[1]
            and region[2] + pad >= box[2] and region[3] + pad >= box[3])


@dataclass(frozen=True)
class TextPair:
    chunk_id: str
    doc_id: str
    value: str
    bbox: list
    start: int
    end: int
    source_ref: str
    single_span: bool
    context: dict


def text_pairs(chunk: dict, labels: set[str]):
    page = chunk["page"]
    if chunk.get("pages") != [page]:
        return
    regions = chunk.get("regions", [])
    bbox = regions[0]["bbox"] if len(regions) == 1 and regions[0]["page"] == page else None
    grounded = not chunk.get("ocr") and not chunk.get("table_id") and valid_box(bbox)
    text = chunk["text"]
    spans = {span["start"]: span for span in chunk.get("source_spans", []) if span["page"] == page}
    offset = 0
    for line in text.splitlines(keepends=True):
        start, end = offset, offset + len(line.rstrip())
        offset += len(line)
        label, _, value = line.partition(":")
        key = label_key(label)
        if key not in labels:
            continue
        # A second occurrence makes this label ambiguous even if only one has a usable span.
        span = spans.get(start + len(line) - len(line.lstrip())) or spans.get(start)
        if not (grounded and span and end <= span["end"] and not text[end:span["end"]].strip() and normalize(value)):
            yield key, None
            continue
        yield key, TextPair(chunk["chunk_id"], chunk["doc_id"], value.strip(), bbox, start, end,
                            span["source_ref"], len(chunk["source_spans"]) == 1, chunk.get("context", {}))


class FormOverlap:
    """Source comparisons shared by the QA ledger and the retrieval writer."""

    def __init__(self, release: Path):
        self.release = release
        self.forms = {form["form_id"]: form for form in read_jsonl(release / "forms.jsonl")}
        fields = defaultdict(list)
        labels = defaultdict(set)
        for form_id, form in self.forms.items():
            page = form["file_id"], form["page"]
            for index, field in enumerate(form["fields"]):
                label = label_key(field["key"])
                if label:
                    fields[(page, label)].append((form_id, index, field))
                    labels[page].add(label)
        self.removed: dict[str, set[int]] = defaultdict(set)
        self.findings: dict[tuple[str, int], list[dict]] = defaultdict(list)
        if not fields:
            return

        pairs = defaultdict(list)
        form_chunks = defaultdict(list)
        for chunk in read_jsonl(release / "chunks.jsonl"):
            page = chunk["file_id"], chunk["page"]
            if chunk["type"] == "form":
                form_chunks[chunk.get("form_id")].append(chunk)
            elif chunk["type"] == "text" and page in labels:
                for label, pair in text_pairs(chunk, labels[page]):
                    pairs[(page, label)].append(pair)

        consistent = {form_id: children[0] for form_id, children in form_chunks.items() if form_id in self.forms
                      and len(children) == 1 and children[0]["text"] == form_text(self.forms[form_id])}
        for (page, label), entries in fields.items():
            alternatives = pairs[(page, label)]
            if len(entries) != 1 or len(alternatives) != 1 or alternatives[0] is None:
                continue
            form_id, index, field = entries[0]
            if form_id in consistent:
                self.compare(page, consistent[form_id], index, field, alternatives[0])

    def compare(self, page: tuple[str, int], chunk: dict, index: int, field: dict, pair: TextPair):
        if (chunk["doc_id"] != pair.doc_id or (chunk["file_id"], chunk["page"]) != page
                or chunk.get("pages") != [page[1]] or chunk.get("context", {}) != pair.context):
            return
        form = self.forms[chunk["form_id"]]
        value = field["value"]
        key_box, value_box = field.get("key_bbox"), field.get("value_bbox")
        if (form.get("rotation", 0) or not field.get("source_word_boxes") or len(value.splitlines()) != 1
                or len(field["key"].splitlines()) != 1
                or not normalize(value) or not all(valid_box(box) and covers(pair.bbox, box) for box in (key_box, value_box))):
            return
        if normalize(value) == normalize(pair.value):
            code = DUPLICATE
            self.removed[chunk["chunk_id"]].add(index)
        else:
            # A broad chunk region can support an exact match but cannot locate a differing value.
            top, bottom = min(key_box[1], value_box[1]), max(key_box[3], value_box[3])
            if not pair.single_span or pair.bbox[3] - pair.bbox[1] > bottom - top + 2 * GEOMETRY_TOLERANCE_PT:
                return
            code = CONFLICT
        self.findings[page].append({
            "code": code, "form_id": form["form_id"], "field_index": index, "label": field["key"],
            "form_value": value, "key_bbox": key_box, "value_bbox": value_box,
            "chunk_id": pair.chunk_id, "chunk_value": pair.value, "chunk_bbox": pair.bbox,
            "chunk_start": pair.start, "chunk_end": pair.end, "source_ref": pair.source_ref,
        })

    def retrieval_rows(self):
        for chunk in read_jsonl(self.release / "chunks.jsonl"):
            text = chunk["text"]
            removed = self.removed.get(chunk["chunk_id"])
            if removed:
                form = self.forms[chunk["form_id"]]
                kept = [field for index, field in enumerate(form["fields"]) if index not in removed]
                if not kept:
                    continue
                text = form_text({"fields": kept})
            yield {**{key: chunk[key] for key in VIEW_KEYS if key in chunk}, "text": text}

    def write_view(self, path: Path) -> int:
        return atomic_write_jsonl(path, self.retrieval_rows())


def register_form_overlap(registry: Registry, load_overlap: Callable[[], FormOverlap]) -> Registry:
    registry.register_reason(DUPLICATE, "INFO", "The full form pair is also present in a source-backed text line.",
                             CHECK)
    registry.register_reason(CONFLICT, "WARN", "A source-backed text line and form give different values for the field.",
                             CHECK)

    def check(context: CheckContext, entity: dict) -> list[dict]:
        if context.validator and context.validator["status"] != "pass":
            return []
        ids = entity["ids"]
        findings = load_overlap().findings.get((ids["file_id"], ids["page"]), ())
        signals = []
        for code in (DUPLICATE, CONFLICT):
            items = [{key: value for key, value in pair.items() if key != "code"}
                     for pair in findings if pair["code"] == code]
            if items:
                signals.append(registry.signal(code, "page", ids, evidence={"pair_count": len(items), "pairs": items}))
        return signals

    registry.register_check(CHECK, check, "page", "1", limitations=(
        "Requires single-page text and one source span for a complete line, source-backed form boxes and a unique label on the page.",
        "Excludes OCR text, rotated forms, tables and multiline pairs. Wider chunk regions only support exact matches.",
        "The two representations can share the same source error. This check does not grant content verification.",
    ))
    return registry
