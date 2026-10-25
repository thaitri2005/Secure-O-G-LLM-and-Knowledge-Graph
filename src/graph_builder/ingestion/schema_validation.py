"""Validate published schemas, canonical spans and shared table references."""
import json
from collections import defaultdict
from pathlib import Path

from jsonschema import Draft202012Validator

from .provenance import content_id
from .tables import tables_path


def validate_artifacts(path: Path) -> list[str]:
    schemas = Path(__file__).resolve().parents[3] / "schemas"
    validators = {name: Draft202012Validator(json.loads((schemas / f"{name}.schema.json").read_text(encoding="utf-8")))
                  for name in ("chunk", "chunk_full", "table", "document")}
    errors = []

    def check(name, record):
        for error in validators[name].iter_errors(record):
            errors.append(f"{name} {record.get('chunk_id', record.get('doc_id', ''))}: {error.json_path}: {error.message}")

    def lines(filename):
        return [json.loads(line) for line in filename.read_text(encoding="utf-8").splitlines()]

    chunks = json.loads(path.read_text(encoding="utf-8"))
    full = lines(path.with_name(path.stem + "_full.jsonl"))
    table_list = lines(tables_path(path))
    tables = {t["table_id"]: t for t in table_list}
    if len(tables) != len(table_list):
        errors.append("Duplicate table_id")
    if len(chunks) != len(full):
        errors.append("Chunk and sidecar lengths differ")
    documents, canonical = {}, {}
    for doc_id in {c["doc_id"] for c in chunks}:
        documents[doc_id] = json.loads((path.parent / "documents" / f"{doc_id}.json").read_text(encoding="utf-8"))
        canonical[doc_id] = (path.parent / "documents" / f"{doc_id}.txt").read_text(encoding="utf-8")
        check("document", documents[doc_id])
        for page in documents[doc_id].get("ocr", {}).get("pages", []):
            if page["status"] == "missing":
                errors.append(f"{doc_id}: scanned page {page['page']} has no attributed OCR content; review required")
    ranges = defaultdict(list)
    for chunk, record in zip(chunks, full):
        check("chunk", chunk)
        check("chunk_full", record)
        if any(record.get(key) != value for key, value in chunk.items()):
            errors.append(f"{chunk['chunk_id']}: sidecar differs from chunk")
        if record.get("content_id") != content_id(chunk):
            errors.append(f"{chunk['chunk_id']}: invalid content_id")
        if canonical[chunk["doc_id"]][record["char_start"]:record["char_end"]] != chunk["text"]:
            errors.append(f"{chunk['chunk_id']}: canonical span mismatch")
        for region in record["regions"]:
            page = documents[chunk["doc_id"]]["pages"].get(str(region["page"]))
            l, t, r, b = region["bbox"]
            if page is None or not (0 <= l < r <= page["width"] and 0 <= t < b <= page["height"]):
                errors.append(f"{chunk['chunk_id']}: invalid region")
        spans = record.get("source_spans")
        if spans is not None:
            position = 0
            for span in spans:
                if span["start"] != position or not span["start"] < span["end"] <= len(chunk["text"]):
                    errors.append(f"{chunk['chunk_id']}: non-contiguous source attribution")
                position = span["end"]
            if position != len(chunk["text"]):
                errors.append(f"{chunk['chunk_id']}: incomplete source attribution")
        refs = record.get("table_refs", [record] if record.get("table_id") else [])
        for ref in refs:
            table = tables.get(ref["table_id"])
            if table is None or table["doc_id"] != chunk["doc_id"] or not (0 <= ref["row_start"] <= ref["row_end"] <= table["num_rows"]):
                errors.append(f"{chunk['chunk_id']}: invalid table reference or row range")
            elif "table_refs" not in record:
                ranges[ref["table_id"]].append((ref["row_start"], ref["row_end"]))
    for table in table_list:
        check("table", table)
        for cell in table["cells"]:
            if cell["r"] + cell["row_span"] > table["num_rows"] or cell["c"] + cell["col_span"] > table["num_cols"]:
                errors.append(f"{table['table_id']}: cell outside table")
        if table["table_id"] in ranges:
            rows = [row for start, end in ranges[table["table_id"]] for row in range(start, end)]
            if rows != list(range(table["rendered_header_rows"], table["num_rows"])):
                errors.append(f"{table['table_id']}: row ranges do not reconstruct the table")
    return errors
