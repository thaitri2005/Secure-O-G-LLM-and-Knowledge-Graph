"""Build the K1 records of one finished corpus document: stable ids, parents, forms, report context, pages and tables.

K1 reads the files a finished document wrote (document.json, chunks.jsonl, tables.jsonl, docling.json.gz) and its
source PDF. The corpus chunk contract and fingerprints do not change; text and offsets are re-derived over the K1 children.
"""
from __future__ import annotations

from collections import Counter
import copy
import gzip
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
from typing import Any

from .catalog import Corpus
from .forms import extract_auto, load_template
from .k1_config import document_type, template_path
from .process import output_directory, page_texts
from .report_context import report_contexts
from .store import read_jsonl

GEOMETRY_KEYS = frozenset({"bbox", "key_bbox", "value_bbox", "width", "height"})


def file_id(sha256: str) -> str:
    return "f" + sha256[:16]


def child_id(parent: str, index: int) -> str:
    return f"{parent}:c{index}"


def canonical(value: Any, geometry: bool = False) -> Any:
    """Round box coordinates and page sizes to 0.01 point; every other value is kept exactly."""
    if isinstance(value, dict):
        return {key: canonical(item, geometry or key in GEOMETRY_KEYS) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical(item, geometry) for item in value]
    if isinstance(value, float) and geometry:
        return round(value, 2) or 0.0
    return value


def form_text(form: dict) -> str:
    """The text of a form chunk; printed labels that already end in a colon keep a single one."""
    return "\n".join(field["key"].rstrip(":") + ": " + field["value"] for field in form["fields"])


def separate_contexts(chunks: list[dict], contexts: dict[int, dict]) -> list[dict]:
    """Split a passage that crosses pages into one chunk per page when the report context differs between them."""
    result = []
    for chunk in chunks:
        signatures = {tuple(sorted(contexts.get(page, {}).items())) for page in chunk["pages"]}
        spans = chunk["source_spans"]
        if len(signatures) <= 1 or not spans:
            result.append(chunk)
            continue
        for page in dict.fromkeys(span["page"] for span in spans):
            selected = [span for span in spans if span["page"] == page]
            start, end = min(s["start"] for s in selected), max(s["end"] for s in selected)
            child = copy.deepcopy(chunk)
            child.update(text=chunk["text"][start:end], page=page, pages=[page],
                         regions=[r for r in chunk["regions"] if r["page"] == page],
                         source_spans=[dict(s, start=s["start"] - start, end=s["end"] - start) for s in selected])
            result.append(child)
    return result


def map_children(fid: str, doc_id: str, dtype: str, chunks: list[dict], tables: list[dict], forms: list[dict],
                 contexts: dict[int, dict]) -> tuple[list[dict], list[dict]]:
    """Turn corpus chunks and forms into K1 children with parents, offsets and digests.

    ``tables`` are the K1 tables (see ``logical_tables``); a table chunk is parented to its table and keeps its
    row range. Every form gets a parent ``<file_id>:f<n>`` and one chunk made of its key-value pairs.
    """
    owners = {table["logical_id"]: table["table_id"] for table in tables}
    parents = {table["table_id"]: dict(parent_id=table["table_id"], type="table", file_id=fid, pages=table["pages"],
                                       section_path=[], document_type=dtype) for table in tables}
    counts = Counter()
    children = []
    previous_path = None
    section = 0
    for original in separate_contexts(chunks, contexts):
        chunk = copy.deepcopy(original)
        if previous_path != chunk["section_path"] or not section:
            section += 1
            previous_path = chunk["section_path"]
        if chunk["table_id"]:
            parent = chunk["table_id"] = owners[chunk["table_id"]]
        else:
            parent = f"{fid}:s{section}"
        parents.setdefault(parent, dict(parent_id=parent, type="section", file_id=fid, pages=[],
                                        section_path=chunk["section_path"], document_type=dtype))
        parents[parent]["pages"] = sorted(set(parents[parent]["pages"]) | set(chunk["pages"]))
        chunk.update(chunk_id=child_id(parent, counts[parent]), file_id=fid, parent_id=parent,
                     child_index=counts[parent], context=contexts.get(chunk["page"], {}), form_id=None)
        counts[parent] += 1
        children.append(chunk)
    for index, form in enumerate(forms, 1):
        parent = f"{fid}:f{index}"
        form.update(form_id=parent, file_id=fid, doc_id=doc_id)
        parents[parent] = dict(parent_id=parent, type="form", file_id=fid, pages=[form["page"]], section_path=[],
                               document_type=dtype)
        regions = [{"page": form["page"], "bbox": field[key]} for field in form["fields"]
                   for key in ("key_bbox", "value_bbox") if field[key]]
        children.append(dict(chunk_id=child_id(parent, 0), file_id=fid, doc_id=doc_id, parent_id=parent,
                             child_index=0, type="form", text=form_text(form), section=None, section_path=[],
                             page=form["page"], pages=[form["page"]], regions=regions, source_spans=[], table_id=None,
                             form_id=parent, row_start=None, row_end=None, language="en", ocr=False,
                             quality="ok" if form["verified"] else "review", context=contexts.get(form["page"], {})))
    position = 0
    for child in children:
        child["char_start"], child["char_end"] = position, position + len(child["text"])
        child["sha256"] = hashlib.sha256(child["text"].encode("utf-8")).hexdigest()
        position = child["char_end"] + 2
    return children, list(parents.values())


def logical_tables(tables: list[dict], document: Any, fid: str, doc_id: str) -> list[dict]:
    """One K1 table per corpus table: a single part, the grid from the Docling table, ids ``<file_id>:t<n>``.

    ``document`` is the DoclingDocument that produced ``tables``. Tables that continue across pages are not joined.
    """
    from ..ingestion.tables import table_views
    native = {table.self_ref: table for table in document.tables}
    result = []
    for number, table in enumerate(tables, 1):
        grid = table_views(native[table["source_ref"]])[0]
        regions = table["regions"]
        pages = sorted({region["page"] for region in regions})
        part = dict(source_ref=table["source_ref"], page=pages[0], bbox=regions[0]["bbox"], row_start=0,
                    row_end=table["num_rows"], header=grid[:table["header_rows"]])
        result.append(dict(table_id=f"{fid}:t{number}", logical_id=table["table_id"], file_id=fid, doc_id=doc_id,
                           pages=pages, grid=grid, header_rows=table["header_rows"], num_rows=table["num_rows"],
                           num_cols=table["num_cols"], cells=table["cells"], parts=[part],
                           join={"status": "single", "reasons": []}, rows_text=table["rows_text"], regions=regions))
    return result


def page_records(fid: str, document: dict, expected: dict[int, str], table_mode: str) -> list[dict]:
    """K1 page rows; ``expected`` holds the page text the chunks must rebuild to, taken before ids were assigned."""
    runtime = document["processing"]["ocr"]["runtime"]
    parser = {"backend": "docling", "version": version("docling"), "table_mode": table_mode}
    records = []
    for page in document["pages"]:
        engine = page["ocr_engine"]
        number = page["page"]
        records.append(dict(page_id=f"{fid}:p{number}", file_id=fid, page=number, width=page["width"],
                            height=page["height"], mode=page["mode"], conversion_mode=page["mode"], parser=parser,
                            ocr={"engine": engine, "version": runtime.get(engine, "")} if engine else None,
                            rotation_attempts=[], status=page["status"],
                            filtered_text_sha256=hashlib.sha256(expected.get(number, "").encode("utf-8")).hexdigest()))
    return records


def context_coverage(chunks: list[dict]) -> dict[str, int]:
    return {"chunks": len(chunks), "with_context": sum(bool(chunk["context"]) for chunk in chunks)}


def build_document(corpus: Corpus, doc: dict, fingerprint: str, k1_config: dict) -> dict[str, Any]:
    """Build every K1 record of one processed PDF document.

    Returns the lists ``files``, ``pages``, ``tables``, ``forms``, ``parents`` and ``chunks``, the extracted
    ``text``, and the report-context findings ``form_conflicts`` and ``pages_without_context``.
    """
    from docling_core.types.doc import DoclingDocument
    directory = output_directory(corpus, doc["doc_id"], fingerprint)
    record = json.loads((directory / "document.json").read_text(encoding="utf-8"))
    chunks = list(read_jsonl(directory / "chunks.jsonl"))
    corpus_tables = list(read_jsonl(directory / "tables.jsonl"))
    pdf = corpus.blob(doc["sha256"])
    fid = file_id(doc["sha256"])
    dtype = document_type(doc["doc_id"], k1_config)
    settings = k1_config["forms"]
    template = load_template(template_path(k1_config))
    numbers = [page["page"] for page in record["pages"]]
    forms = []
    for number in numbers:
        form = extract_auto(pdf, number, template, settings["minimum_label_share"], settings["generic"])
        if form:
            forms.append(dict(form, page=number))
    contexts, conflicts, missing = report_contexts(pdf, numbers, {form["page"]: form for form in forms}, dtype,
                                                   k1_config["report_context"])
    expected = page_texts(chunks + [{"page": form["page"], "source_spans": [], "text": form_text(form)} for form in forms])
    tables = []
    if corpus_tables:
        with gzip.open(directory / "docling.json.gz", "rt", encoding="utf-8") as stream:
            tables = logical_tables(corpus_tables, DoclingDocument.model_validate_json(stream.read()), fid, doc["doc_id"])
    children, parents = map_children(fid, doc["doc_id"], dtype, chunks, tables, forms, contexts)
    pages = page_records(fid, record, expected, corpus.config["table_mode"])
    flagged = {page["page"] for page in pages if page["status"] != "ok"}
    for child in children:
        if flagged.intersection(child["pages"]):
            child["quality"] = "review"
    file = dict(file_id=fid, doc_id=doc["doc_id"], original_name=doc["original_name"], document_type=dtype,
                sha256=doc["sha256"], page_count=len(pages), text=f"text/{fid}.txt",
                license={"id": doc["license_id"], "url": doc["license_url"]})
    return dict(files=[file], pages=pages, tables=tables, forms=forms, parents=parents, chunks=children,
                text="\n\n".join(child["text"] for child in children),
                form_conflicts=[dict(conflict, doc_id=doc["doc_id"]) for conflict in conflicts],
                pages_without_context=[{"doc_id": doc["doc_id"], "page": page} for page in missing])
