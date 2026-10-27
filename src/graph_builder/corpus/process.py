"""Process catalogued documents: analyze pages, convert in segments, chunk, check quality, validate and record.

Each document is processed independently into ``work/<doc_id>/<fingerprint>/``; a ``manifest.json`` written
last marks the output complete. Re-running skips complete documents, resumes partly converted ones from
their cached segments, and isolates failures to the document that caused them.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
import gzip
import hashlib
import json
import logging
import math
import multiprocessing
import os
from pathlib import Path
import shutil
import time
import traceback
from typing import Any, Callable

from .analysis import analyze_pdf, segments
from .catalog import Corpus, now
from .chunking import chunk_document
from .store import atomic_write_json, atomic_write_jsonl, atomic_write_text, file_sha256
from .vietnamese import text_profile

LOGGER = logging.getLogger(__name__)
SUFFIXES = {"pdf": ".pdf", "docx": ".docx", "pptx": ".pptx", "xlsx": ".xlsx", "html": ".html",
            "markdown": ".md", "text": ".md"}
OUTPUTS = ("document.json", "chunks.jsonl", "tables.jsonl", "text.txt", "docling.json.gz")
_CONVERTERS: dict[Any, Any] = {}


def output_directory(corpus: Corpus, doc_id: str, fingerprint: str) -> Path:
    return corpus.work / doc_id / fingerprint


def is_complete(directory: Path) -> bool:
    """True if the manifest exists and every output still has the recorded digest."""
    manifest = directory / "manifest.json"
    if not manifest.is_file():
        return False
    try:
        recorded = json.loads(manifest.read_text(encoding="utf-8"))["files"]
        return all(file_sha256(directory / name) == digest for name, digest in recorded.items())
    except (OSError, ValueError, KeyError):
        return False


def converter(kind: str, mode: str | None, config: dict[str, Any], models: Path):
    """Reuse one converter per (format family, OCR mode) in this process; models load once."""
    key = (kind, mode)
    if key not in _CONVERTERS:
        if kind in ("pdf", "image"):
            from .convert import build_converter
            full_page = {"text": None, "hybrid": False, "ocr": True}[mode]
            _CONVERTERS[key] = build_converter({"ocr": config["ocr"], "table_mode": config["table_mode"],
                                                "document_timeout": config["document_timeout"]}, models, full_page)
        else:
            from docling.datamodel.base_models import InputFormat
            from docling.document_converter import DocumentConverter
            _CONVERTERS[key] = DocumentConverter(allowed_formats=[InputFormat.DOCX, InputFormat.PPTX, InputFormat.XLSX,
                                                                  InputFormat.HTML, InputFormat.MD])
    return _CONVERTERS[key]


def page_confidence(result) -> dict[int, dict[str, float]]:
    scores = {}
    for number, page in (getattr(getattr(result, "confidence", None), "pages", None) or {}).items():
        values = {}
        for name in ("parse_score", "layout_score", "table_score", "ocr_score", "mean_score"):
            value = getattr(page, name, None)
            if isinstance(value, (int, float)) and not math.isnan(value):
                values[name] = round(float(value), 4)
        scores[int(number)] = values
    return scores


def convert_segment(source: Path, kind: str, mode: str, pages: tuple[int, int] | None, cache: Path,
                    config: dict[str, Any], models: Path) -> tuple[Any, dict[str, Any]]:
    from docling.datamodel.base_models import ConversionStatus
    from docling_core.types.doc import DoclingDocument
    meta_path = cache.with_suffix(".meta.json")
    if cache.is_file() and meta_path.is_file():
        with gzip.open(cache, "rt", encoding="utf-8") as stream:
            return DoclingDocument.model_validate_json(stream.read()), json.loads(meta_path.read_text(encoding="utf-8"))
    started = time.perf_counter()
    arguments = {"page_range": pages} if pages else {}
    result = converter(kind, mode, config, models).convert(source, raises_on_error=False, **arguments)
    if result.status not in (ConversionStatus.SUCCESS, ConversionStatus.PARTIAL_SUCCESS):
        errors = "; ".join(str(getattr(error, "error_message", error)) for error in result.errors)[:500]
        raise RuntimeError(f"Conversion {result.status.value} for pages {pages}: {errors}")
    meta = {"mode": mode, "pages": pages, "status": result.status.value,
            "seconds": round(time.perf_counter() - started, 2), "confidence": page_confidence(result),
            "errors": [str(getattr(error, "error_message", error))[:300] for error in result.errors]}
    cache.parent.mkdir(parents=True, exist_ok=True)
    partial = cache.with_name(cache.name + ".partial")
    with gzip.open(partial, "wt", encoding="utf-8", compresslevel=6) as stream:
        stream.write(result.document.model_dump_json())
    os.replace(partial, cache)
    atomic_write_json(meta_path, meta)
    return result.document, meta


def page_texts(chunks: list[dict]) -> dict[int, str]:
    pages: dict[int, list[str]] = {}
    for chunk in chunks:
        if chunk["source_spans"]:
            for span in chunk["source_spans"]:
                pages.setdefault(span["page"], []).append(chunk["text"][span["start"]:span["end"]])
        elif chunk["page"] is not None:
            pages.setdefault(chunk["page"], []).append(chunk["text"])
    return {page: "\n".join(parts) for page, parts in pages.items()}


def assess_pages(pages: list[dict], chunks: list[dict], quality: dict[str, Any]) -> None:
    """Attach the extracted text's spelling profile and an ok/review/missing status to every page."""
    texts = page_texts(chunks)
    for page in pages:
        text = texts.get(page["page"], "")
        profile = text_profile(text)
        characters = len("".join(text.split()))
        status = "ok"
        if page["mode"] == "ocr" and characters < quality["min_ocr_page_chars"]:
            status = "missing"
        elif page["mode"] != "text" and (
                (profile["vietnamese_words"] >= 15
                 and profile["invalid_vietnamese_rate"] > quality["review_invalid_vietnamese_rate"])
                or (profile["words"] >= 15 and profile["foreign_letter_rate"] > quality["review_foreign_letter_rate"])):
            status = "review"
        page.update(extracted_characters=characters, extracted_profile=profile, status=status)


def process_document(root: str, doc: dict[str, Any], config: dict[str, Any], fingerprint: str,
                     ocr: dict[str, Any], models: str) -> dict[str, Any]:
    """Process one catalogued document; runs in a worker process. Returns a summary for the catalog."""
    from docling_core.types.doc import DoclingDocument
    from .validate import validate_document
    corpus = Corpus(Path(root))
    models_path = Path(models)
    directory = output_directory(corpus, doc["doc_id"], fingerprint)
    directory.mkdir(parents=True, exist_ok=True)
    kind = doc["format"]
    source = directory / ("input" + SUFFIXES.get(kind, Path(doc["original_name"]).suffix.lower()))
    if not source.exists():
        try:
            os.link(corpus.blob(doc["sha256"]), source)
        except OSError:
            shutil.copyfile(corpus.blob(doc["sha256"]), source)
    if file_sha256(source) != doc["sha256"]:
        raise ValueError("Stored source does not match its catalogued SHA256")
    started = time.perf_counter()
    if kind == "pdf":
        analysis = [page.to_dict() for page in analyze_pdf(source, config["analysis"])]
        plan = segments([page["mode"] for page in analysis], config["segment_pages"])
    elif kind == "image":
        analysis = [{"page": number, "mode": "ocr", "reasons": ["image_input"]} for number in range(1, (doc["pages"] or 1) + 1)]
        plan = [("ocr", 1, len(analysis))]
    else:
        analysis, plan = [], [("text", 0, 0)]
    documents, metas = [], []
    for mode, first, last in plan:
        cache = directory / "segments" / f"{first:05d}-{last:05d}-{mode}.json.gz"
        pages = (first, last) if kind == "pdf" else None
        document, meta = convert_segment(source, kind if kind in ("pdf", "image") else "office", mode, pages,
                                         cache, config, models_path)
        documents.append(document)
        metas.append(meta)
    merged = documents[0] if len(documents) == 1 else DoclingDocument.concatenate(documents)
    ocr_pages = {page["page"] for page in analysis if page["mode"] in ("ocr", "hybrid")}
    chunks, tables, statistics = chunk_document(merged, doc["doc_id"], config, ocr_pages)
    confidence = {page: scores for meta in metas for page, scores in meta["confidence"].items()}
    for page in analysis:
        page["confidence"] = confidence.get(str(page["page"]), confidence.get(page["page"], {}))
        page["ocr_engine"] = config["ocr"]["engine"] if page["mode"] in ("ocr", "hybrid") else None
    assess_pages(analysis, chunks, config["quality"])
    flagged = {page["page"] for page in analysis if page["status"] != "ok"}
    for chunk in chunks:
        chunk["quality"] = "review" if set(chunk["pages"]) & flagged else "ok"
    text = "\n\n".join(chunk["text"] for chunk in chunks)
    record = {key: doc[key] for key in ("doc_id", "sha256", "bytes", "format", "media_type", "original_name",
                                        "title", "source", "license_id", "license_url")}
    record.update(metadata=json.loads(doc["metadata"]), page_count=len(merged.pages) or None, pages=analysis,
                  processing={"fingerprint": fingerprint, "pipeline": "graph_builder.corpus",
                              "ocr": {"engine": ocr["settings"]["engine"], "runtime": ocr["runtime"],
                                      "models": ocr["models"]},
                              "segments": [{"mode": m["mode"], "pages": m["pages"], "status": m["status"],
                                            "seconds": m["seconds"], "errors": m["errors"]} for m in metas],
                              "seconds": round(time.perf_counter() - started, 2)},
                  statistics=statistics, chunk_count=len(chunks), table_count=len(tables),
                  review_pages=sorted(page["page"] for page in analysis if page["status"] == "review"),
                  missing_pages=sorted(page["page"] for page in analysis if page["status"] == "missing"),
                  text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())
    (directory / "manifest.json").unlink(missing_ok=True)
    atomic_write_jsonl(directory / "chunks.jsonl", chunks)
    atomic_write_jsonl(directory / "tables.jsonl", tables)
    atomic_write_text(directory / "text.txt", text)
    atomic_write_json(directory / "document.json", record)
    partial = directory / "docling.json.gz.partial"
    with gzip.open(partial, "wt", encoding="utf-8", compresslevel=6) as stream:
        stream.write(merged.model_dump_json())
    os.replace(partial, directory / "docling.json.gz")
    errors = validate_document(directory)
    if errors:
        raise ValueError("Output validation failed: " + "; ".join(errors[:5]))
    atomic_write_json(directory / "manifest.json", {"doc_id": doc["doc_id"], "fingerprint": fingerprint,
                                                    "completed_at": now(),
                                                    "files": {name: file_sha256(directory / name) for name in OUTPUTS}})
    source.unlink(missing_ok=True)
    return {"pages": record["page_count"], "chunks": len(chunks), "tables": len(tables),
            "ocr_pages": len(ocr_pages), "review_pages": len(record["review_pages"]),
            "missing_pages": len(record["missing_pages"]), "seconds": record["processing"]["seconds"]}


def _guarded(root: str, doc: dict[str, Any], config: dict[str, Any], fingerprint: str, ocr: dict[str, Any],
             models: str) -> tuple[str, dict[str, Any] | None, str | None]:
    try:
        return "done", process_document(root, doc, config, fingerprint, ocr, models), None
    except Exception as error:  # isolate any failure to this document
        LOGGER.debug("Failure detail for %s:\n%s", doc["doc_id"], traceback.format_exc())
        return "failed", None, f"{type(error).__name__}: {error}"[:1000]


def run(corpus: Corpus, models: Path, workers: int = 1, retry_failed: bool = False, only: list[str] | None = None,
        report: Callable[[str], None] = print) -> dict[str, int]:
    """Process every pending document. Returns counts of done, failed and skipped documents."""
    from .config import fingerprint as make_fingerprint
    from .ocr_engines import engine_fingerprint
    config = corpus.config
    ocr = engine_fingerprint(models, config["ocr"])
    fingerprint = make_fingerprint(config, ocr["models"])
    jobs = corpus.jobs(fingerprint)
    pending, counts = [], {"done": 0, "failed": 0, "skipped": 0}
    for doc in corpus.documents():
        if only and doc["doc_id"] not in only:
            continue
        job = jobs.get(doc["doc_id"])
        complete = job and job["status"] == "done" and is_complete(output_directory(corpus, doc["doc_id"], fingerprint))
        if complete or (job and job["status"] == "failed" and not retry_failed):
            counts["skipped"] += 1
            continue
        pending.append(doc)
    report(f"fingerprint {fingerprint}: {len(pending)} to process, {counts['skipped']} skipped")
    recorded: set[str] = set()

    def record(doc: dict[str, Any], status: str, summary: dict | None, error: str | None, started: str, seconds: float):
        corpus.record_job(doc["doc_id"], fingerprint, status, error, started, seconds, summary)
        recorded.add(doc["doc_id"])
        counts[status] += 1
        detail = json.dumps(summary) if summary else error
        report(f"[{counts['done'] + counts['failed']}/{len(pending)}] {status} {doc['doc_id']}: {detail}")

    arguments = (str(corpus.root),)
    if workers <= 1:
        for doc in pending:
            started, clock = now(), time.perf_counter()
            status, summary, error = _guarded(*arguments, doc, config, fingerprint, ocr, str(models))
            record(doc, status, summary, error, started, time.perf_counter() - clock)
        return counts
    remaining = list(pending)
    while remaining:
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=workers, mp_context=context, max_tasks_per_child=20) as pool:
            started = {}
            futures = {}
            for doc in remaining:
                started[doc["doc_id"]] = (now(), time.perf_counter())
                futures[pool.submit(_guarded, *arguments, doc, config, fingerprint, ocr, str(models))] = doc
            remaining = []
            try:
                for future in as_completed(futures):
                    doc = futures[future]
                    status, summary, error = future.result()
                    record(doc, status, summary, error, started[doc["doc_id"]][0],
                           time.perf_counter() - started[doc["doc_id"]][1])
            except BrokenProcessPool:
                # A worker died (for example out of memory). Fail the documents still running; requeue the rest.
                for future, doc in futures.items():
                    if doc["doc_id"] in recorded:
                        continue
                    if future.running() or future.done():
                        record(doc, "failed", None, "worker process died (possibly out of memory)",
                               started[doc["doc_id"]][0], time.perf_counter() - started[doc["doc_id"]][1])
                    else:
                        remaining.append(doc)
    return counts
