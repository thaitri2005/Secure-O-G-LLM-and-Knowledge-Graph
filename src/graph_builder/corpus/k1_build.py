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
import re
from typing import Any

from .catalog import Corpus
from .forms import extract_auto, load_template
from .k1_config import document_type, template_path
from .ops_tables import RULE, repair_document
from .quarantine import chunk_sidecar
from .process import output_directory, page_texts
from .report_context import document_contexts, report_contexts
from .section_context import clean_path, compile_numbering, hierarchy_path, non_section_values
from .table_join import join_tables
from .store import read_jsonl

GEOMETRY_KEYS = frozenset({"bbox", "key_bbox", "value_bbox", "width", "height"})


class ReportBoundaryError(ValueError):
    """An opt-in boundary guard must hold the document, not publish ambiguous content."""

    def __init__(self, reason: str, **evidence: Any):
        self.evidence = {"reason": reason, **evidence}
        super().__init__(json.dumps(self.evidence, sort_keys=True))


def report_bands(layer: dict, settings: dict) -> list[dict]:
    """Recognize stacked, ruled identity headers directly in PDF geometry.

    Scope: repeated configured well/report/date labels in two adjacent rows inside
    separate rectangular headers. Never infer a boundary from converter order.
    A partially recognized multi-report layout is an error, not a best guess.
    """
    from .forms import find_labels
    from .text_layer import union
    rows = [[w for w in layer["words"] if w["row"] == row] for row in sorted({w["row"] for w in layer["words"]})]
    found = {key: [] for key in settings}
    for row_index, words in enumerate(rows):
        for key, label in settings.items():
            target = label.split()
            for start in range(len(words)):
                if [w["text"] for w in words[start:start + len(target)]] != target:
                    continue
                end = start + len(target)
                other = [p["indices"][0] for p in find_labels(words, None) if p["indices"][0] >= end]
                value = words[end:min(other, default=len(words))]
                found[key].append({"row": row_index, "value": " ".join(w["text"] for w in value),
                                   "bbox": union(words[start:end] + value)})
    if max(len(found[k]) for k in ("well_label", "report_label")) < 2:
        return []
    def reject(reason: str) -> None:
        raise ReportBoundaryError(reason, page=layer["page"], headers=found)
    if layer["rotation"] != 0:
        reject("report_boundary_rotated_frame_unsupported")
    count = len(found["well_label"])
    if count < 2 or any(len(v) != count for v in found.values()):
        reject("report_boundary_incomplete_identity_headers")
    bands = []
    for well, report, date in zip(found["well_label"], found["report_label"], found["date_label"]):
        if report["row"] != well["row"] + 1 or date["row"] != report["row"] or not all(x["value"] for x in (well, report, date)):
            reject("report_boundary_ambiguous_identity_rows")
        box = union([well["bbox"], report["bbox"], date["bbox"]])
        rectangles = [b for b in layer["rulings"] if b[0] <= box[0] and b[1] <= box[1] and b[2] >= box[2] and b[3] >= box[3]]
        if not rectangles:
            reject("report_boundary_missing_ruled_header")
        header = min(rectangles, key=lambda b: (b[2]-b[0])*(b[3]-b[1]))
        if any(header[1] <= b["header"][3] for b in bands):
            reject("report_boundary_overlapping_headers")
        bands.append({"header": header, "identity": [well["value"], date["value"], report["value"]],
                      "context": {"well": well["value"], "report_date": date["value"]}})
    # K1 v1 cannot represent report number. Distinct reports with the same well
    # and date must not be exported with indistinguishable asserted contexts.
    if len({tuple(b["identity"][:2]) for b in bands}) != len(bands):
        reject("report_boundary_duplicate_identity")
    left, _, right, _ = bands[0]["header"]
    if any(abs(b["header"][0]-left) > 1 or abs(b["header"][2]-right) > 1 for b in bands):
        reject("report_boundary_nonstacked_headers")
    edges = [b[3] for b in layer["rulings"] if b[0] <= left + 1 and b[2] >= right - 1 and b[3] > bands[-1]["header"][3]]
    if not edges:
        reject("report_boundary_missing_bottom_rule")
    for index, band in enumerate(bands):
        band["bbox"] = [left-1, band["header"][1], right+1,
                        bands[index+1]["header"][1] if index+1 < len(bands) else max(edges)]
    return bands


def partition_reports(chunks: list[dict], forms: list[dict], document: Any, layers: dict[int, dict],
                      settings: dict, changes: list[dict], tables: list[dict] | None = None) -> tuple[list[dict], list[dict], dict]:
    """Split only at proven source-span ownership boundaries; otherwise hold the document.

    Existing emitted text is sliced, never reinterpreted or reconstructed. Rewritten
    items use their recorded rewrite box, since their raw box is no longer valid.
    The evidence map remains outside K1 rows; the v1 context holds well and date.
    """
    bands = {p: b for p, layer in layers.items() if (b := report_bands(layer, settings))}
    report = {"pages": bands, "slices": [], "forms": []}
    if not bands:
        return chunks, forms, report
    native = {item.self_ref: item for item in [*document.texts, *document.tables]}
    rewrites = {c["ref"]: c for c in changes}

    def owner(page: int, boxes: list[list], ref: str) -> tuple:
        if not boxes:
            raise ReportBoundaryError("report_boundary_missing_provenance", page=page, source_ref=ref)
        owned = set()
        for box in boxes:
            matches = [i for i,b in enumerate(bands[page]) if b["bbox"][0] <= box[0] <= box[2] <= b["bbox"][2]
                       and b["bbox"][1] <= box[1] <= box[3] <= b["bbox"][3]]
            if len(matches) == 1:
                owned.add(matches[0])
            elif box[3] < bands[page][0]["bbox"][1] or box[1] > bands[page][-1]["bbox"][3]:
                owned.add(-1)  # Page preamble/footer is kept separately, without a report assertion.
            else:
                raise ReportBoundaryError("report_boundary_unassigned_box", page=page, source_ref=ref, bbox=box)
        if len(owned) != 1:
            raise ReportBoundaryError("report_boundary_item_crosses_reports", page=page, source_ref=ref, boxes=boxes)
        return page, owned.pop()

    # tables.jsonl is a separate consumer path, including tables with no chunk.
    for table in tables or []:
        keys = {owner(region["page"], [region["bbox"]], table["source_ref"])
                for region in table["regions"] if region["page"] in bands}
        if keys and (len(keys) != 1 or any(region["page"] not in bands for region in table["regions"])):
            raise ReportBoundaryError("report_boundary_table_crosses_reports", source_ref=table["source_ref"])

    result = []
    for chunk in chunks:
        if not set(chunk["pages"]) & bands.keys():
            result.append(chunk)
            continue
        spans = sorted(chunk["source_spans"], key=lambda s: s["start"])
        if not spans or spans[0]["start"] != 0 or spans[-1]["end"] != len(chunk["text"]) or any(a["end"] != b["start"] for a,b in zip(spans,spans[1:])):
            raise ReportBoundaryError("report_boundary_uncovered_text", chunk_id=chunk["chunk_id"], source_spans=spans)
        runs = []
        for span in spans:
            ref, page = span["source_ref"], span["page"]
            boxes = []
            if page not in bands:
                key = page, None
                boxes = [r["bbox"] for r in chunk["regions"] if r["page"] == page]
            else:
                item = native.get(ref)
                if item is None:
                    raise ReportBoundaryError("report_boundary_unknown_source_ref", page=page, source_ref=ref)
                if ref in rewrites:
                    rewrite = rewrites[ref]
                    if rewrite["page"] != page:
                        raise ReportBoundaryError("report_boundary_rewrite_page_mismatch", page=page, source_ref=ref)
                    raw = rewrite["text"]
                    boxes = [rewrite["box"]]
                else:
                    raw = getattr(item, "text", None)
                    for prov in item.prov:
                        if prov.page_no == page and (len(item.prov) == 1 or prov.charspan[0] < span["source_end"] and span["source_start"] < prov.charspan[1]):
                            box = prov.bbox.to_top_left_origin(page_height=document.pages[page].size.height)
                            boxes.append([box.l, box.t, box.r, box.b])
                if raw is not None and re.findall(r"\S+", raw[span["source_start"]:span["source_end"]]) != re.findall(r"\S+", chunk["text"][span["start"]:span["end"]]):
                    raise ReportBoundaryError("report_boundary_source_slice_mismatch", page=page, source_ref=ref, source_span=span)
                key = owner(page, boxes, ref)
            if runs and runs[-1]["key"] == key:
                runs[-1]["spans"].append(span); runs[-1]["boxes"].extend(boxes)
            else:
                runs.append({"key": key, "spans": [span], "boxes": boxes})
        if chunk["type"] != "text" and len(runs) != 1:
            raise ReportBoundaryError("report_boundary_nontext_crosses_reports", chunk_id=chunk["chunk_id"], source_spans=spans)
        for run in runs:
            page,index = run["key"]
            start,end = run["spans"][0]["start"],run["spans"][-1]["end"]
            child = copy.deepcopy(chunk)
            child.update(text=chunk["text"][start:end], page=page, pages=[page],
                         source_spans=[dict(s,start=s["start"]-start,end=s["end"]-start) for s in run["spans"]],
                         regions=[{"page":page,"bbox":box} for box in sorted(set(tuple(b) for b in run["boxes"]))])
            if index is not None:
                child["_report_context"] = bands[page][index]["context"] if index >= 0 else {}
            report["slices"].append({"source_chunk_id":chunk["chunk_id"],"start":start,"end":end,
                                      "page":page,"report_index":index,"source_refs":[s["source_ref"] for s in run["spans"]]})
            result.append(child)
    kept_forms = []
    for form in forms:
        if form["page"] not in bands:
            kept_forms.append(form)
            continue
        # Generic forms can themselves mix reports. Require every field and its
        # enclosing form to have one proven report owner before they enter K1.
        keys = {owner(form["page"], [f[k] for k in ("key_bbox","value_bbox") if f[k]], "form:"+f["key"]) for f in form["fields"]}
        if len(keys) != 1 or next(iter(keys))[1] < 0:
            raise ReportBoundaryError("report_boundary_form_crosses_reports", page=form["page"], fields=form["fields"])
        _, index = keys.pop()
        child = copy.deepcopy(form);child["_report_context"] = bands[form["page"]][index]["context"]
        kept_forms.append(child)
    return result, kept_forms, report


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
                 contexts: dict[int, dict], dropped_sections: dict[str, str] | None = None,
                 numbering: list | None = None, absorbed: dict[str, dict] | None = None,
                 moved: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    """Turn corpus chunks and forms into K1 children with parents, offsets and digests.

    ``tables`` are the K1 tables (see ``logical_tables``); a table chunk is parented to its table and keeps its
    row range. Every form gets a parent ``<file_id>:f<n>`` and one chunk made of its key-value pairs.

    ``dropped_sections`` (optional) lists headings that carry no section information: they are removed from the
    ``section`` and ``section_path`` values of chunks and section parents. ``numbering`` (optional, the compiled
    ``numbered_hierarchy``) gives numbered headings their numbered ancestors in ``section_path``. The section
    numbering behind the ids is still derived from the original paths, so ids do not change.

    ``absorbed`` (optional, from ``table_join``) maps the logical id of a table that joined an earlier one to
    {table_id (its id without the join), owner, offset, dropped, rows}: its chunks are parented to the owner, continue the owner's child
    numbering and take row numbers of the joined grid; text and offsets do not change. ``moved`` (optional list) receives one
    {old_chunk_id, new_chunk_id, old_table_id, new_table_id} per chunk whose id changed.
    """
    owners = {table["logical_id"]: table["table_id"] for table in tables}
    owners.update({logical: entry["owner"] for logical, entry in (absorbed or {}).items()})
    old_counts: Counter = Counter()
    parents = {table["table_id"]: dict(parent_id=table["table_id"], type="table", file_id=fid, pages=table["pages"],
                                       section_path=[], document_type=dtype) for table in tables}
    counts = Counter()
    children = []
    previous_path = None
    section = 0
    numbered: dict = {}
    for original in separate_contexts(chunks, contexts):
        chunk = copy.deepcopy(original)
        context = chunk.pop("_report_context", contexts.get(chunk["page"], {}))
        if previous_path != chunk["section_path"] or not section:
            section += 1
            previous_path = chunk["section_path"]
        if dropped_sections:
            chunk["section_path"] = clean_path(chunk["section_path"], dropped_sections)
            chunk["section"] = chunk["section_path"][-1] if chunk["section_path"] else None
        if numbering and len(chunk["section_path"]) == 1:
            chunk["section_path"] = hierarchy_path(chunk["section_path"][0], numbered, numbering)
        move = (absorbed or {}).get(chunk["table_id"]) if chunk["table_id"] else None
        if chunk["table_id"]:
            parent = chunk["table_id"] = owners[chunk["table_id"]]
            if move:
                for key in ("row_start", "row_end"):
                    if chunk[key] is not None:
                        chunk[key] = move["offset"] + min(max(chunk[key] - move["dropped"], 0), move["rows"])
        else:
            parent = f"{fid}:s{section}"
        parents.setdefault(parent, dict(parent_id=parent, type="section", file_id=fid, pages=[],
                                        section_path=chunk["section_path"], document_type=dtype))
        parents[parent]["pages"] = sorted(set(parents[parent]["pages"]) | set(chunk["pages"]))
        chunk.update(chunk_id=child_id(parent, counts[parent]), file_id=fid, parent_id=parent,
                     child_index=counts[parent], context=context, form_id=None)
        counts[parent] += 1
        if move and moved is not None:
            moved.append(dict(old_chunk_id=child_id(move["table_id"], old_counts[move["table_id"]]), new_chunk_id=chunk["chunk_id"],
                              old_table_id=move["table_id"], new_table_id=parent))
        if move:
            old_counts[move["table_id"]] += 1
        children.append(chunk)
    for index, form in enumerate(forms, 1):
        context = form.pop("_report_context", contexts.get(form["page"], {}))
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
                             quality="ok" if form["verified"] else "review", context=context))
    position = 0
    for child in children:
        child["char_start"], child["char_end"] = position, position + len(child["text"])
        child["sha256"] = hashlib.sha256(child["text"].encode("utf-8")).hexdigest()
        position = child["char_end"] + 2
    return children, list(parents.values())


def logical_tables(tables: list[dict], document: Any, fid: str, doc_id: str) -> list[dict]:
    """One K1 table per corpus table: a single part, the grid from the Docling table, ids ``<file_id>:t<n>``.

    ``document`` is the DoclingDocument that produced ``tables`` (None when every table was rebuilt from the text
    layer). Tables that continue across pages are not joined here (the optional ``table_join`` does that afterwards).
    """
    from ..ingestion.tables import table_views
    native = {table.self_ref: table for table in document.tables} if document is not None else {}
    result = []
    for number, table in enumerate(tables, 1):
        # A table rebuilt from the text layer (ops_tables) brings its own grid and has no Docling item.
        grid = table["grid"] if "grid" in table else table_views(native[table["source_ref"]])[0]
        regions = table["regions"]
        pages = sorted({region["page"] for region in regions})
        part = dict(source_ref=table["source_ref"], page=pages[0], bbox=regions[0]["bbox"], row_start=0,
                    row_end=table["num_rows"], header=grid[:table["header_rows"]])
        result.append(dict(table_id=f"{fid}:t{number}", logical_id=table["table_id"], file_id=fid, doc_id=doc_id,
                           pages=pages, grid=grid, header_rows=table["header_rows"], num_rows=table["num_rows"],
                           num_cols=table["num_cols"], cells=table["cells"], parts=[part],
                           join={"status": "single", "reasons": []}, rows_text=table["rows_text"], regions=regions))
    return result


def table_owners(tables: list[dict], absorbed: dict[str, dict], children: list[dict], moved: list[dict]) -> dict[str, tuple]:
    """logical table id -> (K1 table id, source_ref[, chunk ids]) for the quarantine sidecar. A joined table has several parts: the chunk ids
    keep each part's findings on the chunks of that part (without a join the owner is just (table id, source_ref))."""
    owners: dict[str, tuple] = {t["logical_id"]: (t["table_id"], t["parts"][0]["source_ref"]) for t in tables}
    if absorbed:
        moved_ids = {m["new_chunk_id"] for m in moved}
        for t in tables:
            if t["join"]["status"] == "joined":
                own = {c["chunk_id"] for c in children if c["table_id"] == t["table_id"]} - moved_ids
                owners[t["logical_id"]] = (t["table_id"], t["parts"][0]["source_ref"], own)
        by_old: dict[str, set[str]] = {}
        for m in moved:
            by_old.setdefault(m["old_table_id"], set()).add(m["new_chunk_id"])
        by_ref = {(t["table_id"], part["row_start"]): part["source_ref"] for t in tables for part in t["parts"]}
        for logical, entry in absorbed.items():
            owners[logical] = (entry["owner"], by_ref[(entry["owner"], entry["offset"])], by_old.get(entry["table_id"], set()))
    return owners


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
    ``text``, and the report-context findings ``form_conflicts`` and ``pages_without_context``. ``table_repairs``
    lists, for each table the ``table_rules`` looked at, whether it was rebuilt or why Docling's table was kept.
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
    blocks = k1_config.get("form_blocks")  # optional (A-435): lower form blocks; None keeps the header-only forms
    recognition = k1_config.get("form_recognition")
    recognition_findings: list[dict] = []
    block_findings: list[dict] = []
    for number in numbers:
        if recognition is None:
            form = extract_auto(pdf, number, template, settings["minimum_label_share"], settings["generic"], blocks, block_findings)
        else:
            masks = [region["bbox"] for table in corpus_tables for region in table["regions"] if region["page"] == number]
            form = extract_auto(pdf, number, template, settings["minimum_label_share"], settings["generic"], blocks, block_findings,
                                recognition, recognition_findings, masks)
        if form:
            forms.append(dict(form, page=number))
    block_only = {item["page"] for item in block_findings if item.get("block_only")}
    # Forms that exist only because of the optional blocks are numbered after all other forms, so no existing form id changes.
    forms = [form for form in forms if form["page"] not in block_only] + [form for form in forms if form["page"] in block_only]
    context_forms = forms
    if recognition is not None:
        from .form_recognition import legacy_first
        forms = legacy_first(forms, recognition_findings)
        legacy_counts = {item["page"]: item["legacy_field_count"] for item in recognition_findings if "legacy_field_count" in item}
        # Candidate fields must not change the legacy context/conflict decisions.
        context_forms = [dict(form, fields=form["fields"][:legacy_counts[form["page"]]]) for form in forms if legacy_counts[form["page"]]]
    contexts, conflicts, missing = report_contexts(pdf, numbers, {form["page"]: form for form in context_forms}, dtype,
                                                   k1_config["report_context"])
    # optional: the one well of a document such as an end-of-well report; the types are disjoint from report_context
    single_contexts, single_missing, single_finding = document_contexts(pdf, numbers, dtype, k1_config.get("document_context"))
    if single_finding is not None:
        contexts, missing = single_contexts, single_missing
    repairs = []
    rule = k1_config.get("table_rules", {}).get(RULE)
    if rule and dtype in rule["document_types"]:
        repaired = repair_document(pdf, numbers, chunks, corpus_tables, doc["doc_id"], fid, corpus.config["chunking"]["max_chars"],
                                   rule)
        chunks, corpus_tables = repaired["chunks"], repaired["tables"]
        repairs = [dict(record, document_type=dtype, rule=RULE) for record in repaired["records"]]
    boundary_report = None
    if "report_boundaries" in k1_config:
        from .text_layer import source_page
        try:
            layers = {number: source_page(pdf, number) for number in numbers}
            with gzip.open(directory / "docling.json.gz", "rt", encoding="utf-8") as stream:
                native = DoclingDocument.model_validate_json(stream.read())
            chunks, forms, boundary_report = partition_reports(
                chunks, forms, native, layers, k1_config["report_boundaries"],
                record["statistics"].get("label_value", {}).get("changes", []), corpus_tables)
            if boundary_report["pages"] and k1_config.get("table_join"):
                raise ReportBoundaryError("report_boundary_table_join_combination_unsupported",
                                          pages=sorted(boundary_report["pages"]))
        except ReportBoundaryError:
            raise
        except Exception as error:
            raise ReportBoundaryError("report_boundary_source_unavailable", detail=f"{type(error).__name__}: {error}") from error
    expected = page_texts(chunks + [{"page": form["page"], "source_spans": [], "text": form_text(form)} for form in forms])
    tables = []
    if corpus_tables:
        document = None
        if any("grid" not in table for table in corpus_tables):
            with gzip.open(directory / "docling.json.gz", "rt", encoding="utf-8") as stream:
                document = DoclingDocument.model_validate_json(stream.read())
        tables = logical_tables(corpus_tables, document, fid, doc["doc_id"])
    section_findings = None
    dropped = None
    numbering = None
    options = k1_config.get("section_context")
    if options:
        section_findings = {"dropped": {}, "error": None}
        try:
            dropped = non_section_values(pdf, numbers, {heading for chunk in chunks for heading in chunk["section_path"]}, options)
            section_findings["dropped"] = dropped
            numbering = compile_numbering(options["numbered_hierarchy"]) if "numbered_hierarchy" in options else None
        except Exception as error:  # the text layer could not be read: keep every section, say why
            section_findings["error"] = f"{type(error).__name__}: {error}"
    join_report = None
    absorbed: dict[str, dict] = {}
    moved: list[dict] = []
    if k1_config.get("table_join") and tables:
        # optional (FR-25): tables cut by a page break become one logical table when the evidence is strong; the report is a sidecar
        tables, absorbed, join_report = join_tables(tables, pdf, max(numbers), k1_config["table_join"])
    children, parents = map_children(fid, doc["doc_id"], dtype, chunks, tables, forms, contexts, dropped, numbering, absorbed, moved)
    pages = page_records(fid, record, expected, corpus.config["table_mode"])
    flagged = {page["page"] for page in pages if page["status"] != "ok"}
    for child in children:
        if flagged.intersection(child["pages"]):
            child["quality"] = "review"
    file = dict(file_id=fid, doc_id=doc["doc_id"], original_name=doc["original_name"], document_type=dtype,
                sha256=doc["sha256"], page_count=len(pages), text=f"text/{fid}.txt",
                license={"id": doc["license_id"], "url": doc["license_url"]})
    built = dict(files=[file], pages=pages, tables=tables, forms=forms, parents=parents, chunks=children,
                 text="\n\n".join(child["text"] for child in children), table_repairs=repairs,
                 form_conflicts=[dict(conflict, doc_id=doc["doc_id"]) for conflict in conflicts],
                 pages_without_context=[{"doc_id": doc["doc_id"], "page": page} for page in missing])
    if boundary_report is not None:
        built["report_boundaries"] = boundary_report
    if single_finding is not None:
        built["document_context"] = single_finding
    if "label_value" in record["statistics"]:
        built["label_value"] = record["statistics"]["label_value"]  # optional chunking.label_value: changes and abstentions
    if "quarantine" in record["statistics"]:
        # optional chunking.quarantine: findings, page status, dropped items and the chunk_id join (outside the package)
        built["quarantine"] = {"report": record["statistics"]["quarantine"],
                               **chunk_sidecar(record["statistics"], children, table_owners(tables, absorbed, children, moved))}
    if join_report is not None:
        join_report["chunk_moves"] = moved
        built["table_join"] = join_report
    if section_findings is not None:
        built["section_context"] = section_findings
    if blocks:
        built["form_blocks"] = {"ambiguous_labels": [item for item in block_findings if "label" in item],
                                "errors": [item for item in block_findings if "error" in item],
                                "block_only_pages": sorted(block_only)}
    if recognition is not None:
        built["form_recognition"] = {"version": recognition["version"], "decisions": recognition_findings}
    return built
