"""Check a K1 package: schemas, references, offsets, boxes, page reconstruction, report context and checksums."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any

from .process import page_texts
from .store import file_sha256
from .validate import schema_errors

GROUPS = ("files", "pages", "tables", "forms", "parents", "chunks")
SINGULAR = {"files": "file", "pages": "page", "tables": "table", "forms": "form", "parents": "parent", "chunks": "chunk"}
SUMS = "SHA256SUMS"
MANIFEST = "manifest.json"
LEGACY_MAP = "legacy_chunk_ids.json"
TOLERANCE = 0.01


def read_group(directory: Path, name: str, errors: list[str]) -> list[dict]:
    path = directory / f"{name}.jsonl"
    if not path.is_file():
        errors.append(f"{name}.jsonl: missing")
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def check_checksums(directory: Path, errors: list[str]) -> None:
    sums = directory / SUMS
    if not sums.is_file():
        errors.append(f"{SUMS}: missing")
        return
    listed = set()
    for line in sums.read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        listed.add(name)
        if not (directory / name).is_file():
            errors.append(f"{name}: listed in {SUMS} but missing")
        elif file_sha256(directory / name) != digest:
            errors.append(f"{name}: SHA256 differs from {SUMS}")
    present = {path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file()} - {SUMS}
    errors += [f"{name}: not listed in {SUMS}" for name in sorted(present - listed)]


def check_schemas(sets: dict[str, list[dict]], errors: list[str]) -> dict[str, dict[str, dict]]:
    """Validate every row against its schema and index the rows by id; duplicate ids are errors."""
    index = {}
    for name, rows in sets.items():
        key = SINGULAR[name] + "_id"
        index[name] = {}
        for row in rows:
            label = f"{name} {row.get(key, '?')}"
            errors.extend(schema_errors(f"k1_{SINGULAR[name]}.schema.json", row, label))
            if row.get(key) in index[name]:
                errors.append(f"{name}: duplicate id {row.get(key)}")
            index[name][row.get(key)] = row
    return index


def check_references(sets: dict[str, list[dict]], index: dict[str, dict], errors: list[str]) -> None:
    pages = {(row["file_id"], row["page"]): row for row in sets["pages"] if "page" in row}
    for name in GROUPS[1:]:
        for row in sets[name]:
            label = f"{name} {row.get(SINGULAR[name] + '_id', '?')}"
            if row.get("file_id") not in index["files"]:
                errors.append(f"{label}: missing file reference")
            for number in row.get("pages", [row["page"]] if row.get("page") else []):
                if (row.get("file_id"), number) not in pages:
                    errors.append(f"{label}: missing page reference {number}")
            for region in row.get("regions", []):
                page = pages.get((row.get("file_id"), region["page"]))
                if page is None:
                    errors.append(f"{label}: region on missing page {region['page']}")
                    continue
                left, top, right, bottom = region["bbox"]
                if not (0 <= left <= right <= page["width"] + TOLERANCE and 0 <= top <= bottom <= page["height"] + TOLERANCE):
                    errors.append(f"{label}: region outside page {region['page']}")


def check_chunks(sets: dict[str, list[dict]], index: dict[str, dict], directory: Path, errors: list[str]) -> None:
    texts = {}
    for file_id, row in index["files"].items():
        path = directory / row.get("text", "")
        if path.is_file():
            texts[file_id] = path.read_bytes().decode("utf-8")
        else:
            errors.append(f"files {file_id}: text file missing")
    counters = Counter()
    for chunk in sets["chunks"]:
        label = f"chunks {chunk.get('chunk_id', '?')}"
        parent = index["parents"].get(chunk.get("parent_id"))
        if not parent or parent["file_id"] != chunk.get("file_id"):
            errors.append(f"{label}: invalid parent reference")
        if chunk.get("table_id") and chunk["table_id"] not in index["tables"]:
            errors.append(f"{label}: invalid table reference")
        if chunk.get("form_id") and chunk["form_id"] not in index["forms"]:
            errors.append(f"{label}: invalid form reference")
        if chunk.get("child_index") != counters[chunk.get("parent_id")]:
            errors.append(f"{label}: child indices are not contiguous")
        counters[chunk.get("parent_id")] += 1
        if chunk.get("chunk_id") != f"{chunk.get('parent_id')}:c{chunk.get('child_index')}":
            errors.append(f"{label}: id does not follow its parent and child index")
        file = index["files"].get(chunk.get("file_id"))
        if file and file["doc_id"] != chunk.get("doc_id"):
            errors.append(f"{label}: doc_id differs from its file")
        text = texts.get(chunk.get("file_id"))
        if text is not None and text[chunk["char_start"]:chunk["char_end"]] != chunk["text"]:
            errors.append(f"{label}: text offset mismatch")
        if hashlib.sha256(chunk["text"].encode("utf-8")).hexdigest() != chunk["sha256"]:
            errors.append(f"{label}: sha256 differs from its text")
        for span in chunk["source_spans"]:
            if not 0 <= span["start"] <= span["end"] <= len(chunk["text"]):
                errors.append(f"{label}: source span out of range")


def rebuild_pages(sets: dict[str, list[dict]], errors: list[str]) -> tuple[int, int]:
    """Rebuild each page from its chunks' source spans and compare with the digest recorded for the page."""
    by_file = {}
    for chunk in sets["chunks"]:
        by_file.setdefault(chunk["file_id"], []).append(chunk)
    matches = 0
    for page in sets["pages"]:
        rebuilt = page_texts(by_file.get(page["file_id"], [])).get(page["page"], "")
        if hashlib.sha256(rebuilt.encode("utf-8")).hexdigest() == page["filtered_text_sha256"]:
            matches += 1
        else:
            errors.append(f"pages {page['page_id']}: page rebuild differs")
    return matches, len(sets["pages"])


def check_context(sets: dict[str, list[dict]], index: dict[str, dict], manifest: dict, errors: list[str]) -> dict[str, dict]:
    """Chunks of daily-report files need a report context unless the manifest names their page as an exception."""
    required = set(manifest.get("config", {}).get("k1", {}).get("report_context", {}).get("document_types", []))
    exceptions = {(item["doc_id"], item["page"]) for item in manifest.get("pages_without_context", [])}
    coverage = {}
    for file in sets["files"]:
        if file["document_type"] not in required:
            continue
        chunks = [chunk for chunk in sets["chunks"] if chunk["file_id"] == file["file_id"]]
        coverage[file["doc_id"]] = {"chunks": len(chunks), "with_context": sum(bool(chunk["context"]) for chunk in chunks)}
        for chunk in chunks:
            if not chunk["context"] and (file["doc_id"], chunk["page"]) not in exceptions:
                errors.append(f"chunks {chunk['chunk_id']}: daily report chunk without report_date and well")
    return coverage


def check_legacy_map(directory: Path, index: dict[str, dict], errors: list[str]) -> None:
    path = directory / LEGACY_MAP
    if not path.is_file():
        return
    for row in json.loads(path.read_text(encoding="utf-8")):
        if row.get("new_chunk_id") and row["new_chunk_id"] not in index["chunks"]:
            errors.append(f"{LEGACY_MAP}: {row.get('old_chunk_id')} points to missing chunk {row['new_chunk_id']}")


def inspect(directory: Path) -> dict[str, Any]:
    """Run every check on a staged or published K1 package and return the findings."""
    errors: list[str] = []
    check_checksums(directory, errors)
    sets = {name: read_group(directory, name, errors) for name in GROUPS}
    counts = {name: len(rows) for name, rows in sets.items()}
    manifest = {}
    if (directory / MANIFEST).is_file():
        manifest = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
        if manifest.get("counts") != counts:
            errors.append(f"{MANIFEST}: counts differ from the files")
    else:
        errors.append(f"{MANIFEST}: missing")
    problems = len(errors)
    index = check_schemas(sets, errors)
    matches, total, coverage = 0, len(sets["pages"]), {}
    if len(errors) == problems:
        check_references(sets, index, errors)
        check_chunks(sets, index, directory, errors)
        matches, total = rebuild_pages(sets, errors)
        coverage = check_context(sets, index, manifest, errors)
        check_legacy_map(directory, index, errors)
    return {"status": "pass" if not errors else "fail", "counts": counts, "page_rebuild_matches": matches,
            "page_rebuild_total": total, "context_coverage": coverage, "errors": errors}


def validate_k1(directory: Path) -> list[str]:
    """Problems of a K1 package, for ``publication.publish(validate=...)``; empty when the package is sound."""
    try:
        return inspect(directory)["errors"]
    except (KeyError, TypeError, ValueError, OSError) as error:
        return [f"package could not be read: {type(error).__name__}: {error}"]


def summary(directory: Path) -> dict[str, Any]:
    """Counts, page-rebuild result, context coverage per daily-report file and the list of errors."""
    return inspect(directory)
