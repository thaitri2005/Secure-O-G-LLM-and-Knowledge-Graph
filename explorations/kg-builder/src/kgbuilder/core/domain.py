"""Strict domain graph contracts and streaming verification of authoritative bundles."""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from kgbuilder.core.config import ConfigError, project_path
from kgbuilder.core.project import PROJECT_ROOT
from kgbuilder.core.text import iter_jsonl, sha256_file


class SourceRef(BaseModel):
    """Row identity and allowlisted fields, without fabricated text spans."""
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    member: str
    record_no: int = Field(ge=1)
    key: list[str]
    fields: list[str]


class DomainNode(BaseModel):
    """A namespaced node with row provenance."""
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    id: str
    type: str
    props: dict
    sources: list[SourceRef]


class DomainEdge(BaseModel):
    """A directed typed edge with row provenance."""
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    id: str
    type: str
    source: str
    target: str
    props: dict
    sources: list[SourceRef]


class DomainBundle(BaseModel):
    """Hash-bound manifest of the authoritative domain graph files."""
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    format: Literal["kgb.domain_graph/1"] = "kgb.domain_graph/1"
    snapshot_id: str
    mapping_version: str
    source_manifest_sha256: str
    files: dict[str, str]
    counts: dict[str, int]
    attribution: str


class DomainLink(BaseModel):
    """Hash-bound sidecar; it never changes either source graph."""
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    format: Literal["kgb.domain_link/1"] = "kgb.domain_link/1"
    text_graph_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    doc_sources_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rule_version: str
    files: dict[str, str]
    counts: dict[str, int]


def api12(value: str) -> str:
    """Keep leading zeroes and reject repairs, non-ASCII digits and wrong widths."""
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{12}", value.strip()):
        raise ValueError("invalid API12")
    return value.strip()


def source_id(kind: str, key: tuple[str, ...]) -> str:
    """Build an unambiguous ID from a namespace and textual source keys."""
    return "bsee:" + kind + ":" + ":".join(quote(k, safe="-_.") for k in key)


def read_object(path: Path) -> dict:
    """Read metadata with input-safe diagnostics, never echoing row contents."""
    try:
        result = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (OSError, UnicodeError, ValueError) as exc:
        raise ConfigError(f"invalid metadata: {path.name}") from exc


def run_path(path: Path, key: str = "domain path", exists: bool = True) -> Path:
    """Require domain inputs and outputs strictly below runs/."""
    result = project_path(path, key, exists)
    boundary = PROJECT_ROOT / "runs"
    if result == boundary or not result.is_relative_to(boundary):
        raise ConfigError(f"{key}: must be strictly below runs/")
    return result


def input_path(path: Path, key: str = "domain input") -> Path:
    """Read run artifacts or shipped benchmark/evaluation inputs."""
    result = project_path(path, key, True)
    boundaries = [PROJECT_ROOT / name for name in ("runs", "data/benchmarks/bsee_text", "data/evaluation")]
    if not any(result != root and result.is_relative_to(root) for root in boundaries):
        raise ConfigError(f"{key}: must be below runs/ or a published input directory")
    return result


def output_dir(path: Path, inputs=(), overwrite: bool = False) -> Path:
    """Check overlap and emptiness before any output mutation."""
    target = run_path(path, "output", False)
    for source in inputs:
        source = project_path(source, "input", True)
        if target.is_relative_to(source) or source.is_relative_to(target):
            raise ConfigError("output overlaps an input")
    if target.exists():
        if not target.is_dir():
            raise ConfigError("output is not a directory")
        if any(target.iterdir()):
            if not overwrite:
                raise ConfigError("nonempty output requires --overwrite")
            shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    return target


def verify_bundle(root: Path) -> DomainBundle:
    """Verify hashes, schema, sorted uniqueness and endpoints with disk-backed IDs."""
    root = project_path(root, "domain bundle", True)
    try:
        bundle = DomainBundle.model_validate(read_object(root / "graph.json"))
    except ValidationError as exc:
        raise ConfigError("invalid domain bundle contract") from exc
    required = {"nodes.jsonl", "edges.jsonl", "sources.jsonl", "unresolved.jsonl"}
    if set(bundle.files) != required:
        raise ConfigError("domain bundle file inventory mismatch")
    for name, digest in bundle.files.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file() or sha256_file(path) != digest:
            raise ConfigError(f"domain bundle hash/containment mismatch: {name}")
    staging = PROJECT_ROOT / ".cache/tmp/bsee"
    staging.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=staging, prefix="verify_") as temporary:
        db = sqlite3.connect(Path(temporary) / "ids.sqlite")
        try:
            db.execute("PRAGMA cache_size=-65536")
            db.execute("CREATE TABLE nodes(id TEXT PRIMARY KEY)")
            counts = {}
            for name, model in [("nodes.jsonl", DomainNode), ("edges.jsonl", DomainEdge),
                                ("sources.jsonl", None), ("unresolved.jsonl", None)]:
                count = 0
                previous = None
                for row in iter_jsonl(root / name):
                    count += 1
                    identity = row.get("id")
                    if not isinstance(identity, str) or (previous is not None and identity <= previous):
                        raise ConfigError(f"domain bundle IDs not sorted and unique: {name}:record {count}")
                    previous = identity
                    if model:
                        model.model_validate(row)
                    if name == "nodes.jsonl":
                        db.execute("INSERT INTO nodes VALUES (?)", (identity,))
                    elif name == "edges.jsonl":
                        for endpoint in (row["source"], row["target"]):
                            if not db.execute("SELECT 1 FROM nodes WHERE id=?", (endpoint,)).fetchone():
                                raise ConfigError(f"dangling endpoint: record {count}")
                    elif name == "sources.jsonl":
                        SourceRef.model_validate({k: v for k, v in row.items() if k != "id"})
                counts[name.removesuffix(".jsonl")] = count
            if counts != bundle.counts:
                raise ConfigError("domain bundle counts mismatch")
        except (ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            raise ConfigError("invalid domain bundle record") from exc
        finally:
            db.close()
    return bundle
