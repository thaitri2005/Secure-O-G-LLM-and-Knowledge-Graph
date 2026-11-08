"""Check a K1 version 0 chunk file: every row against the schema, then the rules a schema cannot express.

Usage: python platform/validate_k1.py [chunks.jsonl]   (default: data/processed/gdr_chunks_full.jsonl)
Exit code 0 when every chunk passes, 1 otherwise.
"""
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "k1_chunk.v0.schema.json"
DEFAULT = ROOT / "data" / "processed" / "gdr_chunks_full.jsonl"


def check_rows(rows):
    """Return a list of (line number, chunk ID, problem) for every rule a row breaks."""
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    problems, seen = [], {}
    for line, row in rows:
        chunk_id = row.get("chunk_id", "?") if isinstance(row, dict) else "?"
        for error in validator.iter_errors(row):
            where = "/".join(str(part) for part in error.path) or "row"
            problems.append((line, chunk_id, f"{where}: {error.message}"))
        if not isinstance(row, dict):
            continue
        # Rules across fields or rows, which JSON Schema cannot check.
        if chunk_id in seen:
            problems.append((line, chunk_id, f"duplicate chunk_id, first on line {seen[chunk_id]}"))
        seen.setdefault(chunk_id, line)
        doc_id = row.get("doc_id")
        if isinstance(chunk_id, str) and isinstance(doc_id, str) and not chunk_id.startswith(doc_id + "#c"):
            problems.append((line, chunk_id, f"chunk_id does not start with its doc_id '{doc_id}#c'"))
        table_id = row.get("table_id")
        if isinstance(table_id, str) and isinstance(doc_id, str) and not table_id.startswith(doc_id + "#t"):
            problems.append((line, chunk_id, f"table_id does not start with its doc_id '{doc_id}#t'"))
        start, end = row.get("row_start"), row.get("row_end")
        if isinstance(start, int) and isinstance(end, int) and end < start:
            problems.append((line, chunk_id, f"row_end {end} is before row_start {start}"))
        pages, page = row.get("pages"), row.get("page")
        if isinstance(pages, list) and pages and isinstance(page, int) and page != min(pages):
            problems.append((line, chunk_id, f"page {page} is not the first of pages {pages}"))
    return problems


def read_jsonl(path):
    """Yield (line number, parsed row); a line that is not JSON becomes a string row, which the schema rejects."""
    with open(path, encoding="utf-8") as handle:
        for number, text in enumerate(handle, start=1):
            if text.strip():
                try:
                    yield number, json.loads(text)
                except json.JSONDecodeError as error:
                    yield number, f"not JSON: {error}"


def main(argv):
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT
    rows = list(read_jsonl(path))
    problems = check_rows(rows)
    failed = {line for line, _, _ in problems}
    for line, chunk_id, message in problems:
        print(f"line {line} ({chunk_id}): {message}")
    print(f"{path.name}: {len(rows)} chunks checked, {len(rows) - len(failed)} passed, {len(failed)} failed")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
