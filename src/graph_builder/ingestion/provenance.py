"""Preserve canonical character spans and PDF source geometry."""
from __future__ import annotations

from collections import defaultdict
import hashlib
from importlib.metadata import version
import json
from pathlib import Path

from pypdf import PdfReader
import pypdfium2
import pypdfium2.raw as pdfium

from .sources import write_json, write_text


def rounded_geometry(value):
    """Copy artifact metadata at 0.01-point precision without changing text or integer spans."""
    if isinstance(value, float):
        # JSON must not distinguish positive and negative zero after rounding.
        return round(value, 2) or 0.0
    if isinstance(value, dict):
        return {key: rounded_geometry(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [rounded_geometry(item) for item in value]
    return value


def content_id(chunk: dict) -> str:
    normalized = " ".join(chunk["text"].split())
    value = "|".join((chunk.get("doc_id", ""), chunk.get("type", ""), normalized))
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def merge_regions(regions: list[dict], heights: dict[int, float]) -> list[dict]:
    pages = defaultdict(list)
    for region in regions:
        pages[region["page"]].append(region["bbox"])
    merged = []
    for page, boxes in sorted(pages.items()):
        current = None
        for box in sorted(boxes, key=lambda value: (value[1], value[0])):
            if current is None or box[1] - current[3] > heights[page] / 3:
                current = list(box)
                merged.append({"page": page, "bbox": current})
            else:
                current[:] = [min(current[0], box[0]), min(current[1], box[1]), max(current[2], box[2]), max(current[3], box[3])]
    return merged


def item_regions(document, items: list) -> list[dict]:
    regions = []
    for item, selected_page in items:
        for prov in item.prov:
            if selected_page is not None and prov.page_no != selected_page:
                continue
            size = document.pages[prov.page_no].size
            box = prov.bbox.to_top_left_origin(page_height=size.height)
            regions.append({"page": prov.page_no, "bbox": [box.l, box.t, box.r, box.b]})
    return merge_regions(regions, {page: value.size.height for page, value in document.pages.items()})


def rectangle_area(boxes: list[list[float]]) -> float:
    edges = sorted({x for l, b, r, t in boxes for x in (l, r)})
    area = 0.0
    for left, right in zip(edges, edges[1:]):
        intervals = sorted((b, t) for l, b, r, t in boxes if l <= left and right <= r)
        end = float("-inf")
        for bottom, top in intervals:
            area += (right - left) * max(0, top - max(bottom, end))
            end = max(end, top)
    return area


def page_records(pdf: Path, needs_ocr_pages: list[int] | None = None) -> dict:
    reader = PdfReader(pdf)
    records = {}
    with pypdfium2.PdfDocument(pdf) as rendered:
        for number, page in enumerate(reader.pages, 1):
            view = rendered[number - 1]
            width, height = view.get_size()
            sparse = needs_ocr_pages is None and len((page.extract_text() or "").strip()) < 50
            boxes = [list(item.get_bounds()) for item in view.get_objects(filter=[pdfium.FPDF_PAGEOBJ_IMAGE])] if sparse else []
            records[str(number)] = {"width": width, "height": height, "rotation": int(page.rotation),
                                    "needs_ocr": (number in needs_ocr_pages if needs_ocr_pages is not None
                                                  else sparse and rectangle_area(boxes) > width * height / 2)}
            view.close()
    return records


def canonical_records(chunks: list[dict], metadata: list[dict], parent_doc_id: str | None) -> tuple[str, list[dict]]:
    if len(chunks) != len(metadata):
        raise ValueError("Every chunk requires provenance metadata")
    canonical = "\n\n".join(chunk["text"] for chunk in chunks)
    position, records = 0, []
    for chunk, extra in zip(chunks, metadata):
        records.append({**chunk, **extra, "content_id": content_id(chunk), "char_start": position, "char_end": position + len(chunk["text"]),
                        "parent_doc_id": parent_doc_id})
        position += len(chunk["text"]) + 2
    return canonical, records


def write_document(root: Path, directory: Path, source: dict, chunks: list[dict], metadata: list[dict], options: dict) -> list[dict]:
    doc_id = source["doc_id"]
    marked = None
    inventory = root / "data/interim/scan_inventory.json"
    if inventory.exists():
        for scan in json.loads(inventory.read_text(encoding="utf-8")):
            if scan["doc_id"] == doc_id and scan.get("sha256") == source.get("sha256"):
                marked = scan["needs_ocr"]
    pages = page_records(root / "data/raw" / f"{doc_id}.pdf", marked)
    record = {key: source.get(key) for key in ("doc_id", "title", "landing_page", "gdr_submission", "license", "sha256", "bytes", "parent_doc_id")}
    record.update(source_url=source.get("url"), page_count=len(pages), pages=pages,
                  parser=f"docling {version('docling')}",
                  config_hash=hashlib.sha256(json.dumps(options, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
    if "original_filename" in source:
        record["original_filename"] = source["original_filename"]
    if options.get("do_ocr"):
        from .ocr_settings import ocr_settings
        counts = defaultdict(int)
        for chunk, extra in zip(chunks, metadata):
            spans = extra.get("source_spans", [])
            if spans:
                for span in spans:
                    counts[span["page"]] += len(chunk["text"][span["start"]:span["end"]].strip())
            else:
                counts[chunk["page"]] += len(chunk["text"].strip())
        record["ocr"] = {"settings": ocr_settings(options), "pages": [
            {"page": int(number), "attributed_characters": counts[int(number)],
             "status": ("missing" if counts[int(number)] == 0 else "review")
                       if page["needs_ocr"] and counts[int(number)] < 40 else "covered"}
            for number, page in pages.items()]}
    write_json(directory / "documents" / f"{doc_id}.json", rounded_geometry(record))
    canonical, full = canonical_records(chunks, metadata, source.get("parent_doc_id"))
    write_text(directory / "documents" / f"{doc_id}.txt", canonical)
    return full
