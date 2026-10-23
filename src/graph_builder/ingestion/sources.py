"""Load source registries and pipeline options, verify downloads, and serialize portable JSON artifacts."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, BinaryIO
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pypdf import PdfReader

DOC_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
USER_AGENT = "graph-builder-ingestion/0.1 (+https://github.com/thaitri2005/Secure-O-G-LLM-and-Knowledge-Graph)"


def write_text(path: Path, text: str) -> None:
    """Write portable UTF-8 text, including when the input already uses CRLF."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.replace("\r\n", "\n").replace("\r", "\n"), encoding="utf-8", newline="\n")


def write_json(path: Path, value: Any) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_checksums(directory: Path, doc_ids: list[str]) -> None:
    """Hash exactly one registry's deliverable, excluding other local bundles."""
    manifest = directory / "SHA256SUMS"
    paths = [directory / name for name in ("gdr_chunks.json", "gdr_chunks_full.jsonl", "gdr_tables.jsonl")]
    paths.extend(directory / "documents" / f"{doc_id}{suffix}" for doc_id in doc_ids for suffix in (".json", ".txt"))
    paths.sort(key=lambda path: path.relative_to(directory).as_posix())
    write_text(manifest, "".join(f"{sha256(path)}  {path.relative_to(directory).as_posix()}\n" for path in paths))


def check_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "gdr.openei.org":
        raise ValueError(f"Only https://gdr.openei.org downloads are supported: {url}")


class GdrRedirects(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_gdr(url: str) -> BinaryIO:
    check_url(url)
    return build_opener(GdrRedirects()).open(Request(url, headers={"User-Agent": USER_AGENT}), timeout=120)


def load_registry(path: Path) -> list[dict[str, Any]]:
    registry = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(registry, list) or not registry:
        raise ValueError("Source registry must be a nonempty array")
    seen = set()
    required = {"doc_id", "title", "well", "gdr_submission", "url", "landing_page", "license", "sha256", "bytes"}
    for source in registry:
        if not isinstance(source, dict) or required - source.keys():
            raise ValueError("Source registry entry has missing fields")
        doc_id = source["doc_id"]
        if not isinstance(doc_id, str) or not DOC_ID.fullmatch(doc_id) or doc_id in seen:
            raise ValueError(f"Invalid or duplicate doc_id: {doc_id!r}")
        seen.add(doc_id)
        check_url(source["url"])
        check_url(source["landing_page"])
        if type(source["gdr_submission"]) is not int or source["gdr_submission"] < 1:
            raise ValueError("gdr_submission must be a positive integer")
        if type(source["bytes"]) is not int or source["bytes"] < 1 or not re.fullmatch(r"[a-f0-9]{64}", source["sha256"]):
            raise ValueError("Source must pin positive bytes and a SHA256 digest")
        if not isinstance(source["license"], dict) or set(source["license"]) != {"id", "url"}:
            raise ValueError("License must have an id and URL")
    return registry


def load_options(path: Path, overrides: list[str] | None = None) -> dict[str, Any]:
    options = json.loads(path.read_text(encoding="utf-8"))
    for override in overrides or []:
        key, separator, value = override.partition("=")
        if not separator:
            raise ValueError("Overrides must use key=value")
        target = options
        parts = key.split(".")
        for part in parts[:-1]:
            if part not in target or not isinstance(target[part], dict):
                raise ValueError(f"Unknown option: {key}")
            target = target[part]
        if parts[-1] not in target:
            raise ValueError(f"Unknown option: {key}")
        try:
            target[parts[-1]] = json.loads(value)
        except json.JSONDecodeError:
            target[parts[-1]] = value
    required = {"max_chars", "do_ocr", "do_table_structure", "table_mode", "do_cell_matching", "device", "margin_band", "frequency", "spot_checks",
                "running_block_max_gap_lines", "running_block_alignment_lines", "running_line_fragment_gap_lines",
                "chunking", "tables"}
    if not isinstance(options, dict) or set(options) != required:
        raise ValueError(f"Pipeline options must contain exactly {sorted(required)}")
    if type(options["max_chars"]) is not int or options["max_chars"] < 1:
        raise ValueError("max_chars must be a positive integer")
    for key in ("do_ocr", "do_table_structure", "do_cell_matching"):
        if type(options[key]) is not bool:
            raise ValueError(f"{key} must be a boolean")
    if options["do_ocr"] or options["device"] != "cpu":
        raise ValueError("This pipeline supports CPU conversion without OCR")
    if options["table_mode"] not in {"accurate", "fast"}:
        raise ValueError("table_mode must be accurate or fast")
    if options["chunking"] not in ({"strategy": name} for name in ("page", "paragraph", "hybrid", "pypdf")):
        raise ValueError("chunking.strategy must be page, paragraph, hybrid or pypdf")
    if (not isinstance(options["tables"], dict)
            or set(options["tables"]) != {"compact", "merge_pages", "rotation_retry"}
            or any(type(value) is not bool for value in options["tables"].values())):
        raise ValueError("tables must contain boolean compact, merge_pages and rotation_retry options")
    for key, limit in (("margin_band", 0.5), ("frequency", 1)):
        if type(options[key]) not in (int, float) or not 0 < options[key] <= limit:
            raise ValueError(f"{key} must be between 0 (exclusive) and {limit}")
    for key in ("running_block_max_gap_lines", "running_block_alignment_lines"):
        if type(options[key]) not in (int, float) or not 0 <= options[key] <= 1:
            raise ValueError(f"{key} must be between 0 and 1")
    if type(options["running_line_fragment_gap_lines"]) not in (int, float) or options["running_line_fragment_gap_lines"] < 0:
        raise ValueError("running_line_fragment_gap_lines must be nonnegative")
    if not isinstance(options["spot_checks"], list):
        raise ValueError("spot_checks must be an array")
    for check in options["spot_checks"]:
        if (not isinstance(check, dict) or set(check) != {"doc_id", "page", "section", "contains"}
                or not isinstance(check["doc_id"], str) or type(check["page"]) is not int or check["page"] < 1
                or not isinstance(check["section"], str) or not isinstance(check["contains"], list)
                or not all(isinstance(term, str) for term in check["contains"])):
            raise ValueError("Invalid content spot check")
    return options


def project_root(config_path: Path) -> Path:
    for parent in config_path.resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    if (Path.cwd() / "pyproject.toml").is_file():
        return Path.cwd()
    raise ValueError("Cannot locate the project root from the config location or working directory")


def verify_file(path: Path, source: dict[str, Any]) -> None:
    if path.stat().st_size != source["bytes"] or sha256(path) != source["sha256"]:
        raise ValueError(f"Source size or SHA256 mismatch: {path.name}")


def fetch_sources(registry: list[dict[str, Any]], root: Path) -> list[dict[str, Any]]:
    raw = root / "data" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    records = []
    for source in registry:
        path = raw / f"{source['doc_id']}.pdf"
        cached = path.exists()
        if cached:
            verify_file(path, source)
        else:
            partial = path.with_suffix(".pdf.part")
            try:
                with open_gdr(source["url"]) as response, partial.open("wb") as stream:
                    for block in iter(lambda: response.read(1024 * 1024), b""):
                        stream.write(block)
                verify_file(partial, source)
                PdfReader(partial)
                partial.replace(path)
            finally:
                partial.unlink(missing_ok=True)
        records.append({"doc_id": source["doc_id"], "bytes": source["bytes"], "sha256": source["sha256"], "cached": cached})
    write_json(raw / "download_log.json", {"checked_at": datetime.now(timezone.utc).isoformat(), "sources": records})
    return records
