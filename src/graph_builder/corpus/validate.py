"""Check one document's outputs: schemas, offsets, digests, page geometry and table references."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path

SCHEMAS = Path(__file__).resolve().parents[3] / "schemas"


@lru_cache(maxsize=None)
def validator(name: str):
    from jsonschema import Draft202012Validator
    schema = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def schema_errors(name: str, record: dict, label: str) -> list[str]:
    return [f"{label}: {error.json_path}: {error.message}"[:300] for error in validator(name).iter_errors(record)]


def validate_document(directory: Path, max_errors: int = 50) -> list[str]:
    errors: list[str] = []
    document = json.loads((directory / "document.json").read_text(encoding="utf-8"))
    errors += schema_errors("corpus_document.schema.json", document, "document")
    doc_id = document["doc_id"]
    text = (directory / "text.txt").read_text(encoding="utf-8")
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != document["text_sha256"]:
        errors.append("text.txt does not match text_sha256")
    sizes = {page["page"]: (page.get("width"), page.get("height")) for page in document["pages"]}
    tables = {}
    with (directory / "tables.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            table = json.loads(line)
            errors += schema_errors("corpus_table.schema.json", table, table.get("table_id", "table"))
            tables[table["table_id"]] = table
    expected_start, count = 0, 0
    with (directory / "chunks.jsonl").open(encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            chunk = json.loads(line)
            label = chunk.get("chunk_id", f"chunk {index}")
            errors += schema_errors("corpus_chunk.schema.json", chunk, label)
            count += 1
            if chunk["chunk_id"] != f"{doc_id}#c{index:05d}" or chunk["doc_id"] != doc_id:
                errors.append(f"{label}: unexpected identifier")
            if (chunk["char_start"], chunk["char_end"]) != (expected_start, expected_start + len(chunk["text"])):
                errors.append(f"{label}: offsets do not follow the previous chunk")
            elif text[chunk["char_start"]:chunk["char_end"]] != chunk["text"]:
                errors.append(f"{label}: text.txt slice differs from chunk text")
            expected_start = chunk["char_end"] + 2
            if hashlib.sha256(chunk["text"].encode("utf-8")).hexdigest() != chunk["sha256"]:
                errors.append(f"{label}: sha256 mismatch")
            for region in chunk["regions"]:
                width, height = sizes.get(region["page"], (None, None))
                left, top, right, bottom = region["bbox"]
                if width and height and not (-1 <= left <= right <= width + 1 and -1 <= top <= bottom <= height + 1):
                    errors.append(f"{label}: region outside page {region['page']}")
            for span in chunk["source_spans"]:
                if not 0 <= span["start"] <= span["end"] <= len(chunk["text"]):
                    errors.append(f"{label}: source span outside chunk text")
            if document["page_count"] and any(not 1 <= page <= document["page_count"] for page in chunk["pages"]):
                errors.append(f"{label}: page outside the document")
            if chunk["type"] == "table":
                table = tables.get(chunk["table_id"])
                if table is None:
                    errors.append(f"{label}: unknown table {chunk['table_id']}")
                elif not 0 <= chunk["row_start"] <= chunk["row_end"] <= table["num_rows"]:
                    errors.append(f"{label}: row range outside table")
            if len(errors) >= max_errors:
                return errors
    if count != document["chunk_count"] or len(tables) != document["table_count"]:
        errors.append("chunk or table count differs from document.json")
    if document["page_count"] and document["pages"] and len(document["pages"]) != document["page_count"]:
        errors.append("page analysis does not cover every page")
    return errors
