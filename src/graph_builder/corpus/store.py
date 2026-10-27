"""Content-addressed storage of original source files and atomic artifact writes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Iterable

CHUNK = 1024 * 1024


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def blob_path(store: Path, digest: str) -> Path:
    return store / digest[:2] / digest[2:4] / digest


def put_blob(store: Path, source: Path, digest: str | None = None) -> tuple[str, Path]:
    """Copy a file into the store under its SHA256; identical content is stored once."""
    digest = digest or file_sha256(source)
    target = blob_path(store, digest)
    if target.is_file():
        if target.stat().st_size != source.stat().st_size:
            raise ValueError(f"Store corruption: {target} has the wrong size")
        return digest, target
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False, prefix=".partial-") as handle:
        partial = Path(handle.name)
    try:
        shutil.copyfile(source, partial)
        if file_sha256(partial) != digest:
            raise ValueError(f"{source} changed while it was being stored")
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return digest, target


def atomic_write_text(path: Path, text: str) -> None:
    """Write UTF-8 LF text so that readers see either the old or the complete new file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent,
                                     delete=False, prefix=".partial-") as handle:
        handle.write(text.replace("\r\n", "\n").replace("\r", "\n"))
        partial = Path(handle.name)
    os.replace(partial, path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n")


def atomic_write_jsonl(path: Path, records: Iterable[Any]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent,
                                     delete=False, prefix=".partial-") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
        partial = Path(handle.name)
    os.replace(partial, path)
    return count


def read_jsonl(path: Path) -> Iterable[Any]:
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)
