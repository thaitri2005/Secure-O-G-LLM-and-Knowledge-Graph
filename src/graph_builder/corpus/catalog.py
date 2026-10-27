"""Corpus catalog: one SQLite database per corpus recording sources, their stored copies and processing jobs."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
from typing import Any, Iterator
import unicodedata
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .formats import FORMATS, UnsupportedFormat, check_pdf, detect_format, page_count
from .store import atomic_write_json, file_sha256, put_blob

DOC_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    bytes INTEGER NOT NULL,
    format TEXT NOT NULL,
    media_type TEXT NOT NULL,
    pages INTEGER,
    original_name TEXT NOT NULL,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    license_id TEXT NOT NULL,
    license_url TEXT NOT NULL,
    metadata TEXT NOT NULL,
    added_at TEXT NOT NULL,
    retired INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS jobs (
    doc_id TEXT NOT NULL REFERENCES documents(doc_id),
    fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('done', 'failed')),
    attempts INTEGER NOT NULL,
    error TEXT,
    started_at TEXT,
    finished_at TEXT,
    seconds REAL,
    summary TEXT,
    PRIMARY KEY (doc_id, fingerprint)
);
CREATE TABLE IF NOT EXISTS rejected (
    path TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    checked_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slug(text: str, limit: int = 48) -> str:
    """ASCII document-ID prefix from a file name; Vietnamese letters lose their marks (đ -> d)."""
    text = unicodedata.normalize("NFKD", text.replace("đ", "d").replace("Đ", "D"))
    text = "".join(char for char in text if not unicodedata.combining(char)).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:limit].strip("-") or "doc"


class Corpus:
    """A corpus directory: config.json, catalog.sqlite, store/ (originals), work/ (derived), exports/."""

    def __init__(self, root: Path):
        self.root = root
        self.store = root / "store"
        self.work = root / "work"
        self.exports = root / "exports"
        if not (root / "catalog.sqlite").is_file():
            raise ValueError(f"{root} is not a corpus; run `python -m graph_builder.corpus init {root}`")

    @staticmethod
    def create(root: Path, config: dict[str, Any]) -> "Corpus":
        root.mkdir(parents=True, exist_ok=True)
        if (root / "config.json").exists():
            raise ValueError(f"{root} already contains a corpus")
        atomic_write_json(root / "config.json", config)
        connection = sqlite3.connect(root / "catalog.sqlite")
        try:
            connection.executescript(SCHEMA)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.commit()
        finally:
            connection.close()
        return Corpus(root)

    @property
    def config(self) -> dict[str, Any]:
        from .config import validate_config
        return validate_config(json.loads((self.root / "config.json").read_text(encoding="utf-8")))

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.root / "catalog.sqlite", timeout=60)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def documents(self, include_retired: bool = False) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM documents" + ("" if include_retired else " WHERE retired = 0")
                                      + " ORDER BY doc_id").fetchall()
        return [dict(row) for row in rows]

    def jobs(self, fingerprint: str) -> dict[str, dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM jobs WHERE fingerprint = ?", (fingerprint,)).fetchall()
        return {row["doc_id"]: dict(row) for row in rows}

    def record_job(self, doc_id: str, fingerprint: str, status: str, error: str | None,
                   started: str, seconds: float, summary: dict[str, Any] | None) -> None:
        with self.connect() as connection:
            previous = connection.execute("SELECT attempts FROM jobs WHERE doc_id = ? AND fingerprint = ?",
                                          (doc_id, fingerprint)).fetchone()
            connection.execute(
                "INSERT OR REPLACE INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (doc_id, fingerprint, status, (previous["attempts"] if previous else 0) + 1,
                 error, started, now(), round(seconds, 2), json.dumps(summary) if summary else None))

    def blob(self, sha256: str) -> Path:
        from .store import blob_path
        return blob_path(self.store, sha256)

    def add_file(self, path: Path, title: str | None = None, doc_id: str | None = None, source: str | None = None,
                 license_id: str = "unspecified", license_url: str = "",
                 metadata: dict[str, Any] | None = None) -> tuple[str, str]:
        """Register one file. Returns (status, doc_id or reason) where status is added, duplicate or rejected."""
        path = path.resolve()
        limits = self.config["limits"]
        try:
            size = path.stat().st_size
            if not 0 < size <= limits["max_bytes"]:
                raise UnsupportedFormat(f"size {size} bytes is outside 1..{limits['max_bytes']}")
            kind = detect_format(path)
            if kind == "pdf":
                check_pdf(path)
            pages = page_count(path, kind)
            if pages is not None and pages > limits["max_pages"]:
                raise UnsupportedFormat(f"{pages} pages exceeds the limit of {limits['max_pages']}")
        except (UnsupportedFormat, OSError) as error:
            with self.connect() as connection:
                connection.execute("INSERT OR REPLACE INTO rejected VALUES (?, ?, ?)", (str(path), str(error), now()))
            return "rejected", str(error)
        digest = file_sha256(path)
        with self.connect() as connection:
            existing = connection.execute("SELECT doc_id FROM documents WHERE sha256 = ?", (digest,)).fetchone()
            if existing:
                return "duplicate", existing["doc_id"]
        doc_id = doc_id or f"{slug(path.stem)}-{digest[:8]}"
        if not DOC_ID.fullmatch(doc_id):
            raise ValueError(f"Invalid document ID {doc_id!r}")
        put_blob(self.store, path, digest)
        with self.connect() as connection:
            connection.execute("DELETE FROM rejected WHERE path = ?", (str(path),))
            connection.execute(
                "INSERT INTO documents (doc_id, sha256, bytes, format, media_type, pages, original_name, title, source,"
                " license_id, license_url, metadata, added_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (doc_id, digest, size, kind, FORMATS[kind][1], pages, path.name, title or path.stem,
                 source or path.as_posix(), license_id, license_url, json.dumps(metadata or {}, ensure_ascii=False),
                 now()))
        return "added", doc_id

    def add_url(self, url: str, sha256: str | None = None, **fields: Any) -> tuple[str, str]:
        """Download from an allow-listed HTTPS host, verify an optional pinned digest, then register."""
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in self.config["allowed_hosts"]:
            raise ValueError(f"Only HTTPS downloads from allowed_hosts {self.config['allowed_hosts']} are permitted")
        limit = self.config["limits"]["max_bytes"]
        name = Path(parsed.path).name or "download"
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / name
            request = Request(url, headers={"User-Agent": "graph-builder-corpus/1"})
            with urlopen(request, timeout=300) as response, target.open("wb") as stream:
                if urlparse(response.geturl()).hostname not in self.config["allowed_hosts"]:
                    raise ValueError(f"Redirect left the allowed hosts: {response.geturl()}")
                copied = 0
                while block := response.read(1024 * 1024):
                    copied += len(block)
                    if copied > limit:
                        raise ValueError(f"Download exceeds {limit} bytes")
                    stream.write(block)
            if sha256 and file_sha256(target) != sha256:
                raise ValueError(f"SHA256 mismatch for {url}")
            return self.add_file(target, source=url, **fields)

    def retire(self, doc_id: str) -> None:
        with self.connect() as connection:
            if connection.execute("UPDATE documents SET retired = 1 WHERE doc_id = ?", (doc_id,)).rowcount != 1:
                raise ValueError(f"Unknown document {doc_id}")


def iter_files(paths: list[Path], recursive: bool) -> Iterator[Path]:
    for path in paths:
        if path.is_dir():
            pattern = "**/*" if recursive else "*"
            yield from sorted(p for p in path.glob(pattern) if p.is_file() and not p.name.startswith("."))
        elif path.is_file():
            yield path
        else:
            raise ValueError(f"No such file or directory: {path}")


def copy_tree_atomic(source: Path, destination: Path) -> None:
    """Replace a directory so readers never see a half-written export."""
    staging = destination.with_name(destination.name + ".old")
    if staging.exists():
        shutil.rmtree(staging)
    if destination.exists():
        destination.rename(staging)
    source.rename(destination)
    if staging.exists():
        shutil.rmtree(staging)
