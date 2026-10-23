"""Measure extraction fidelity against spatially filtered PDF text."""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import re
import statistics

from docling_core.types.doc import DoclingDocument
from pypdf import PdfReader
from pypdf._text_extraction import mult

from .filters import dropped_item_reasons, filter_running_lines
from .runs import conversion_cache, run_directory
from .sources import sha256, write_checksums, write_json
from .text_packing import chunk_spans


def normalize_numbers(text: str) -> str:
    text = re.sub(r"(?<=\d)\s*,\s*(?=\d)", "", text)
    return re.sub(r"(?<=\d)[ \t]+(?=\d)", "", text)


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[^\W_]+", normalize_numbers(text).casefold()))


def quantities(text: str) -> set[str]:
    pattern = r"(?<![\w.])\d+(?:\.\d+)?\s*(?:lb\s*/\s*ft|feet|ft|psi|ppg|bbl|gpm|in|[\u00b0]\s*[fc]|%|'|\")(?=\W|$)"
    return {re.sub(r"\s+", "", match).casefold() for match in re.findall(pattern, normalize_numbers(text), re.I)}


def exclusion_regions(document: DoclingDocument, options: dict) -> list[dict]:
    filtered, _ = filter_running_lines(document, options["margin_band"], options["frequency"],
                                      options["running_block_max_gap_lines"], options["running_block_alignment_lines"],
                                      options["running_line_fragment_gap_lines"])
    excluded = dropped_item_reasons(document)
    regions = []
    from .validate import exempt_pages
    for page in exempt_pages(document, options):
        size = document.pages[page].size
        regions.append({"page": page, "bbox": [0, 0, size.width, size.height]})
    for item in [*document.texts, *document.tables, *document.pictures]:
        # Picture rectangles may contain retained captions and PDF text.
        if excluded.get(item.self_ref) == "picture":
            continue
        removed = bool(getattr(item, "text", "")) and not getattr(item.get_ref().resolve(filtered), "text", "")
        if item.self_ref not in excluded and not removed:
            continue
        for prov in item.prov:
            box = prov.bbox.to_top_left_origin(page_height=document.pages[prov.page_no].size.height)
            regions.append({"page": prov.page_no, "bbox": [box.l, box.t, box.r, box.b]})
    for original, cleaned in zip(document.tables, filtered.tables):
        for before, after in zip(original.data.table_cells, cleaned.data.table_cells):
            if before.text.strip() and not after.text.strip() and before.bbox and len(original.prov) == 1:
                page = original.prov[0].page_no
                box = before.bbox.to_top_left_origin(page_height=document.pages[page].size.height)
                regions.append({"page": page, "bbox": [box.l, box.t, box.r, box.b]})
    return regions


def reference_text(page, regions: list[dict]) -> str:
    pieces = []
    height = float(page.mediabox.height)

    def visit(text, cm, tm, font, size):
        matrix = mult(tm, cm)
        x, y = matrix[4], height - matrix[5]
        rotation = getattr(page, "rotation", 0) % 360
        if rotation == 90:
            x, y = height - y, x
        elif rotation == 180:
            x, y = float(page.mediabox.width) - x, height - y
        elif rotation == 270:
            x, y = y, float(page.mediabox.width) - x
        if not any(l - 1 <= x <= r + 1 and t - 1 <= y <= b + 1 for l, t, r, b in (r["bbox"] for r in regions)):
            pieces.append(text)

    page.extract_text(visitor_text=visit)
    return "".join(pieces)


def naive_chunks(registry: list[dict], root: Path, max_chars: int) -> list[dict]:
    chunks = []
    for source in registry:
        doc_id = source["doc_id"]
        index = 0
        for number, page in enumerate(PdfReader(root / "data/raw" / f"{doc_id}.pdf").pages, 1):
            text = (page.extract_text() or "").strip()
            for start, end in chunk_spans(text, max_chars):
                chunks.append({"doc_id": doc_id, "page": number, "chunk_id": f"{doc_id}#c{index:04d}",
                               "type": "text", "text": text[start:end], "section": None})
                index += 1
    return chunks


def fidelity(reference: str, extracted: str) -> dict:
    expected, actual = tokens(reference), tokens(extracted)
    intersection = expected & actual
    expected_q, actual_q = quantities(reference), quantities(extracted)
    return {"word_recall": len(intersection) / len(expected) if expected else None,
            "word_precision": len(intersection) / len(actual) if actual else (0.0 if expected else None),
            "reference_words": len(expected), "extracted_words": len(actual),
            "quantity_count": len(expected_q), "quantity_matches": len(expected_q & actual_q),
            "missed_quantities": sorted(expected_q - actual_q), "missed_words": sorted(expected - actual)}


def repeated_lines(document: DoclingDocument) -> set[str]:
    occurrences = defaultdict(set)
    for item in document.texts:
        for line in item.text.splitlines():
            key = re.sub(r"\d+", "#", " ".join(line.casefold().split()))
            if key:
                occurrences[key].update(prov.page_no for prov in item.prov)
    return {line for line, pages in occurrences.items() if len(pages) >= len(document.pages) * .5}


def evaluate_run(root: Path, name: str) -> dict:
    directory = run_directory(root, name)
    options = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    registry = json.loads((directory / "sources.json").read_text(encoding="utf-8"))
    chunks = json.loads((directory / "gdr_chunks.json").read_text(encoding="utf-8"))
    sidecar_path = directory / "gdr_chunks_full.jsonl"
    full = [json.loads(line) for line in sidecar_path.read_text(encoding="utf-8").splitlines()] if sidecar_path.exists() else []
    by_page = defaultdict(list)
    from .attribution import page_texts
    for chunk in full or chunks:
        for page, text in page_texts(chunk).items():
            by_page[chunk["doc_id"], page].append(text)
    pages, leakage, documents = [], [], {}
    for source in registry:
        doc_id = source["doc_id"]
        document = DoclingDocument.model_validate_json((conversion_cache(root, options) / f"{doc_id}.json").read_text(encoding="utf-8"))
        documents[doc_id] = document
        excluded = exclusion_regions(document, options)
        recurring = repeated_lines(document)
        for number, page in enumerate(PdfReader(root / "data/raw" / f"{doc_id}.pdf").pages, 1):
            reference = reference_text(page, [r for r in excluded if r["page"] == number])
            extracted = "\n".join(by_page[doc_id, number])
            pages.append({"doc_id": doc_id, "page": number, "substantive": len(reference.strip()) > 200,
                          **fidelity(reference, extracted)})
            lines = {re.sub(r"\d+", "#", " ".join(line.casefold().split())) for line in extracted.splitlines()}
            for line in sorted(recurring & lines):
                leakage.append({"doc_id": doc_id, "page": number, "line": line})
    recalls = [p["word_recall"] for p in pages if p["word_recall"] is not None]
    substantive = [p["word_recall"] for p in pages if p["substantive"] and p["word_recall"] is not None]
    precisions = [p["word_precision"] for p in pages if p["word_precision"] is not None]
    quantity_count = sum(p["quantity_count"] for p in pages)
    texts = [c for c in chunks if c["type"] == "text"]
    offset_matches, valid_boxes, boxes = 0, 0, 0
    document_records = {source["doc_id"]: json.loads((directory / "documents" / f"{source['doc_id']}.json").read_text(encoding="utf-8"))
                        for source in registry}
    for chunk in full:
        canonical = (directory / "documents" / f"{chunk['doc_id']}.txt").read_text(encoding="utf-8")
        offset_matches += canonical[chunk["char_start"]:chunk["char_end"]] == chunk["text"]
        record = document_records[chunk["doc_id"]]
        for region in chunk["regions"]:
            boxes += 1
            page = record["pages"][str(region["page"])]
            l, t, r, b = region["bbox"]
            valid_boxes += 0 <= l < r <= page["width"] and 0 <= t < b <= page["height"]
    timing_path = directory / "timings.json"
    timings = json.loads(timing_path.read_text(encoding="utf-8")) if timing_path.exists() else []
    from .validate import load_sources, validate_records
    errors, warnings, coverage = validate_records(chunks, [source["doc_id"] for source in registry],
                                                  load_sources(registry, root, conversion_cache(root, options)), options, full)
    from .schema_validation import validate_artifacts
    errors.extend(validate_artifacts(directory / "gdr_chunks.json"))
    from .chunking import chunk_documents
    repeat = directory / "repeated_chunks.json"
    try:
        _, chunking_statistics = chunk_documents(registry, root, options, output=repeat, cache=conversion_cache(root, options))
        deterministic = repeat.read_bytes() == (directory / "gdr_chunks.json").read_bytes()
    finally:
        repeat.unlink(missing_ok=True)
        repeat.with_name(repeat.stem + "_full.jsonl").unlink(missing_ok=True)
        from .tables import tables_path
        tables_path(repeat).unlink(missing_ok=True)
    gold = None
    registry_has_gold = False
    if (root / "data/gold/ingestion/tables.json").exists():
        from .scoring import supplement_gold
        from .tables import tables_path
        tables = [json.loads(line) for line in tables_path(directory / "gdr_chunks.json").read_text(encoding="utf-8").splitlines()]
        annotations = json.loads((root / "data/gold/ingestion/tables.json").read_text(encoding="utf-8"))
        registry_has_gold = any(annotation["doc_id"] in documents for annotation in annotations)
        gold = supplement_gold(root, tables, list(full), documents, options)
    from .validate import single_oversized_row
    write_checksums(directory, [source["doc_id"] for source in registry])
    result = {"word_recall_median": statistics.median(recalls) if recalls else None, "word_recall_min": min(recalls) if recalls else None,
              "substantive_recall_median": statistics.median(substantive) if substantive else None,
              "substantive_recall_min": min(substantive) if substantive else None, "gold": gold,
              "registry_has_gold": registry_has_gold,
              "chunking_statistics": chunking_statistics,
              "oversized_single_row_warnings": sum(c["type"] == "table" and len(c["text"]) > options["max_chars"]
                                                    and single_oversized_row(c["text"], options["max_chars"]) for c in chunks),
              "word_precision_median": statistics.median(precisions) if precisions else None,
              "quantity_recall": sum(p["quantity_matches"] for p in pages) / quantity_count if quantity_count else None,
              "quantity_count": quantity_count, "header_footer_leakage": leakage,
              "short_text_chunks": sum(len(c["text"]) < 200 for c in texts),
              "mid_sentence_chunks": sum(c["text"].rstrip()[-1] not in ".!?:" for c in texts),
              "text_chunks": len(texts), "chunks": len(chunks),
              "offset_match_rate": offset_matches / len(full) if full else None,
              "valid_bbox_rate": valid_boxes / boxes if boxes else None,
              "deterministic": deterministic, "determinism_scope": "cached conversion, repeated chunking", "sha256": sha256(directory / "gdr_chunks.json"),
              "manifest_sha256": sha256(directory / "SHA256SUMS"),
              "scanned_pages": sum(page["needs_ocr"] for record in document_records.values() for page in record["pages"].values()),
              "seconds_per_page": sum(t["docling_seconds"] for t in timings) / len(pages) if timings else None,
              "validated": not errors and bool(full) and offset_matches == len(full) and valid_boxes == boxes and deterministic,
              "validation_errors": errors, "validation_warnings": warnings, "coverage": coverage, "pages": pages}
    write_json(directory / "metrics.json", result)
    return {key: value for key, value in result.items() if key not in {"pages", "header_footer_leakage", "coverage", "validation_warnings"}}
