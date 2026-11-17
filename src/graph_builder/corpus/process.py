"""Process catalogued documents: analyze pages, convert in segments, chunk, check quality, validate and record.

Each document is processed independently into ``work/<doc_id>/<fingerprint>/``; a ``manifest.json`` written
last marks the output complete. Re-running skips complete documents, resumes partly converted ones from
their cached segments, and isolates failures to the document that caused them.
"""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
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
import threading
import time
import traceback
from typing import Any, Callable

from .analysis import analyze_pdf, segments
from .catalog import Corpus, now
from .chunking import chunk_document
from .label_value import label_value_settings, mark_unverified
from .orientation import UPRIGHT_COPY, apply_page_orientation
from .quarantine import mark_quarantine, quarantine_settings
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


MARKER = "job.running.json"
STATES = ("completed", "failed", "interrupted", "not_started")


def marker_path(directory: Path) -> Path:
    return directory / MARKER


def read_marker(directory: Path) -> dict[str, Any] | None:
    """The marker a worker leaves while it processes a document, or None. An unreadable marker still means it started."""
    path = marker_path(directory)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {"state": "running"}
    except (OSError, ValueError):
        return {"state": "running", "unreadable": True}


def write_marker(directory: Path, doc_id: str, fingerprint: str, state: str) -> None:
    atomic_write_json(marker_path(directory), {"doc_id": doc_id, "fingerprint": fingerprint, "state": state,
                                               "pid": os.getpid(), "at": now()})


def clear_marker(directory: Path) -> None:
    try:
        marker_path(directory).unlink(missing_ok=True)
    except OSError:
        pass  # a leftover marker next to a complete manifest is ignored (see document_state)


def document_state(directory: Path, job: dict[str, Any] | None, verify: bool = True) -> tuple[str, str]:
    """One of ``STATES`` for a document and fingerprint, with a machine-readable reason.

    completed: the manifest and every output digest are intact. failed: the catalog holds a failure. interrupted: a
    worker started the document and never reported (killed, or the whole run died). not_started: nothing usable exists.
    ``verify=False`` only checks that the manifest exists (cheap, for ``status``); ``run`` always verifies the digests.
    """
    complete = is_complete(directory) if verify else (directory / "manifest.json").is_file()
    if complete:
        return "completed", "recorded" if job and job["status"] == "done" else "unrecorded"
    if read_marker(directory) is not None:
        return "interrupted", "started_without_finishing"
    if job and job["status"] == "failed":
        return "failed", "recorded_failure"
    return "not_started", "output_missing_or_changed" if job else "pending"


def summarize(record: dict[str, Any]) -> dict[str, Any]:
    """The catalog summary of a processed document, derived from its document.json record."""
    return {"pages": record["page_count"], "chunks": record["chunk_count"], "tables": record["table_count"],
            "ocr_pages": sum(page["mode"] in ("ocr", "hybrid") for page in record["pages"]),
            "review_pages": len(record["review_pages"]), "missing_pages": len(record["missing_pages"]),
            "seconds": record["processing"]["seconds"]}


def completed_summary(directory: Path) -> dict[str, Any]:
    """Summary of an intact output directory whose catalog record is missing (the process died before writing it)."""
    return summarize(json.loads((directory / "document.json").read_text(encoding="utf-8")))


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
    if not (cache.is_file() and meta_path.is_file()):
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
        LOGGER.info("  %s pages %s (%s): %s in %.1f s", source.parent.parent.name, pages or "all", mode,
                    meta["status"], meta["seconds"])
    # Both paths read the cache back so a cold run and a cached run give the same document and metadata.
    with gzip.open(cache, "rt", encoding="utf-8") as stream:
        document = DoclingDocument.model_validate_json(stream.read())
    return document, json.loads(meta_path.read_text(encoding="utf-8"))


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


class SourceChecksumError(ValueError):
    """The working copy of a source cannot be made to match the SHA256 in the catalog.

    ``reason`` is a stable code; the message starts with it (``SourceChecksumError: <reason>: ...`` in the catalog's
    job error and in ``status``): ``source_checksum_mismatch_store`` means the blob in the store itself is wrong,
    ``source_work_copy_replace_failed`` means the stale working copy could not be replaced (for example it is locked).
    """

    def __init__(self, reason: str, detail: str):
        super().__init__(f"{reason}: {detail}")
        self.reason, self.detail = reason, detail

    def __reduce__(self):  # survives a trip between worker and parent process
        return type(self), (self.reason, self.detail)


def ensure_source(corpus: Corpus, doc: dict[str, Any], source: Path) -> None:
    """Make ``source`` (the working copy in the output directory) a file whose SHA256 equals the catalogued one.

    A copy left by an earlier attempt (a failed or killed run) is reused only if it still matches; otherwise it is
    rebuilt from the store through ``<source>.partial`` and published with ``os.replace``, so the name ``source``
    never holds an unchecked file. If the store's own blob does not match, no wrong file is left behind and the
    blob is not touched (a hard link is only unlinked).
    """
    expected, blob = doc["sha256"], corpus.blob(doc["sha256"])
    if source.is_file() and file_sha256(source) == expected:
        return
    partial = source.with_name(source.name + ".partial")
    partial.unlink(missing_ok=True)
    try:
        os.link(blob, partial)
    except OSError:
        shutil.copyfile(blob, partial)
    actual = file_sha256(partial)
    try:
        if actual != expected:
            partial.unlink(missing_ok=True)
            source.unlink(missing_ok=True)  # a derived file already known to be wrong; the blob is not this path
            raise SourceChecksumError("source_checksum_mismatch_store",
                                      f"store blob {blob.as_posix()} has sha256 {actual}, catalog expects {expected}")
        os.replace(partial, source)
    except OSError as error:
        raise SourceChecksumError("source_work_copy_replace_failed", f"{type(error).__name__}: {error}") from error


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
    ensure_source(corpus, doc, source)
    started = time.perf_counter()
    if kind == "pdf":
        analysis = [page.to_dict() for page in analyze_pdf(source, config["analysis"])]
        plan = segments([page["mode"] for page in analysis], config["segment_pages"])
    elif kind == "image":
        analysis = [{"page": number, "mode": "ocr", "reasons": ["image_input"]} for number in range(1, (doc["pages"] or 1) + 1)]
        plan = [("ocr", 1, len(analysis))]
    else:
        analysis, plan = [], [("text", 0, 0)]
    conversion_source = source
    orientation_settings = config["analysis"].get("page_orientation") if kind == "pdf" else None
    if orientation_settings:  # optional (C-03): record page orientation; "normalize" converts a copy with upright pages
        conversion_source = apply_page_orientation(source, directory, analysis, orientation_settings)
    documents, metas = [], []
    for mode, first, last in plan:
        cache = directory / "segments" / f"{first:05d}-{last:05d}-{mode}.json.gz"
        pages = (first, last) if kind == "pdf" else None
        document, meta = convert_segment(conversion_source, kind if kind in ("pdf", "image") else "office", mode, pages,
                                         cache, config, models_path)
        documents.append(document)
        metas.append(meta)
    merged = documents[0] if len(documents) == 1 else DoclingDocument.concatenate(documents)
    ocr_pages = {page["page"] for page in analysis if page["mode"] in ("ocr", "hybrid")}
    chunks, tables, statistics = chunk_document(merged, doc["doc_id"], config, ocr_pages, source if kind == "pdf" else None)
    confidence = {page: scores for meta in metas for page, scores in meta["confidence"].items()}
    for page in analysis:
        converted = merged.pages.get(page["page"])
        if converted is not None:
            # Docling reports the displayed (rotation-applied) size; regions use the same frame.
            page["width"], page["height"] = round(converted.size.width, 2), round(converted.size.height, 2)
        page["confidence"] = confidence.get(str(page["page"]), confidence.get(page["page"], {}))
        page["ocr_engine"] = config["ocr"]["engine"] if page["mode"] in ("ocr", "hybrid") else None
    assess_pages(analysis, chunks, config["quality"])
    flagged = {page["page"] for page in analysis if page["status"] != "ok"}
    for chunk in chunks:
        chunk["quality"] = "review" if set(chunk["pages"]) & flagged else "ok"
    if "label_value" in config["chunking"]:  # optional (C-01c): chunks with a label-value item left unverified are marked "review"
        mark_unverified(chunks, statistics, label_value_settings(config["chunking"]["label_value"]))
    if "quarantine" in config["chunking"]:  # optional (P2-WP1): chunks with a quarantine finding are marked "review" when mark_review is on
        mark_quarantine(chunks, statistics, quarantine_settings(config["chunking"]["quarantine"]))
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
    (directory / UPRIGHT_COPY).unlink(missing_ok=True)
    return summarize(record)


def guarded_call(task: Callable[..., dict[str, Any]], root: str, doc: dict[str, Any], config: dict[str, Any],
                 fingerprint: str, ocr: dict[str, Any], models: str) -> tuple[str, dict[str, Any] | None, str | None]:
    """Run ``task`` for one document, isolating its exceptions and leaving a marker while it runs.

    The marker is removed when the task returns or raises an ordinary exception. If the process is killed (out of
    memory, the machine stops) or interrupted by the user, the marker stays and the document reads as ``interrupted``.
    """
    directory = None
    try:
        directory = output_directory(Corpus(Path(root)), doc["doc_id"], fingerprint)
        write_marker(directory, doc["doc_id"], fingerprint, "running")
        outcome = "done", task(root, doc, config, fingerprint, ocr, models), None
    except Exception as error:  # isolate any failure to this document
        LOGGER.debug("Failure detail for %s:\n%s", doc["doc_id"], traceback.format_exc())
        outcome = "failed", None, f"{type(error).__name__}: {error}"[:1000]
    if directory is not None:
        clear_marker(directory)
    return outcome


def _guarded(root: str, doc: dict[str, Any], config: dict[str, Any], fingerprint: str, ocr: dict[str, Any],
             models: str) -> tuple[str, dict[str, Any] | None, str | None]:
    return guarded_call(process_document, root, doc, config, fingerprint, ocr, models)


def run(corpus: Corpus, models: Path, workers: int = 1, retry_failed: bool = False, only: list[str] | None = None,
        report: Callable[[str], None] = print, heartbeat: float = 60.0) -> dict[str, int]:
    """Process every incomplete document and return counts.

    done, failed and skipped as before; ``not_started`` counts the documents no worker could start (the pool died
    before they began). Only completed documents are skipped; a failed one is retried with ``retry_failed``;
    interrupted and not-started ones are always picked up again by the next run.
    """
    from .config import fingerprint as make_fingerprint
    from .ocr_engines import engine_fingerprint
    config = corpus.config
    ocr = engine_fingerprint(models, config["ocr"])
    fingerprint = make_fingerprint(config, ocr["models"])
    jobs = corpus.jobs(fingerprint)
    pending, counts = [], {"done": 0, "failed": 0, "skipped": 0, "not_started": 0}
    resumed = adopted = 0
    for doc in corpus.documents():
        if only and doc["doc_id"] not in only:
            continue
        directory = output_directory(corpus, doc["doc_id"], fingerprint)
        state, reason = document_state(directory, jobs.get(doc["doc_id"]))
        if state == "completed":
            if reason == "unrecorded":  # finished, but the process died before the catalog was updated: keep the output
                summary = completed_summary(directory)
                corpus.record_job(doc["doc_id"], fingerprint, "done", None, now(), summary["seconds"], summary)
                clear_marker(directory)
                adopted += 1
            counts["skipped"] += 1
            continue
        if state == "failed" and not retry_failed:
            counts["skipped"] += 1
            continue
        resumed += state == "interrupted"
        pending.append(doc)
    total_pages = sum(doc["pages"] or 1 for doc in pending)
    report(f"fingerprint {fingerprint}: {len(pending)} documents ({total_pages} pages) to process, "
           f"{counts['skipped']} already done, {workers} worker(s)"
           + (f"; {resumed} were interrupted by an earlier run and start again" if resumed else "")
           + (f"; {adopted} complete outputs had no catalog record and were recorded" if adopted else ""))
    recorded: set[str] = set()
    clock = time.perf_counter()
    done_pages = 0

    active: dict[str, tuple[float, int]] = {}  # doc_id -> (start time, pages) for documents being worked on
    stop = threading.Event()

    def beat():
        while not stop.wait(heartbeat):
            elapsed = time.perf_counter() - clock
            running = ", ".join(f"{doc_id} ({pages} pages, {(time.perf_counter() - start) / 60:.1f} min)"
                                for doc_id, (start, pages) in sorted(active.items())) or "none"
            report(f"... still working: {counts['done'] + counts['failed']}/{len(pending)} documents, "
                   f"pages {done_pages}/{total_pages}, elapsed {elapsed / 60:.1f} min; in progress: {running}")

    def record(doc: dict[str, Any], status: str, summary: dict | None, error: str | None, started: str, seconds: float):
        nonlocal done_pages
        active.pop(doc["doc_id"], None)
        if summary and summary.get("seconds"):
            seconds = summary["seconds"]  # the worker's own time, excluding time spent queued
        corpus.record_job(doc["doc_id"], fingerprint, status, error, started, seconds, summary)
        recorded.add(doc["doc_id"])
        counts[status] += 1
        done_pages += doc["pages"] or 1
        elapsed = time.perf_counter() - clock
        eta = elapsed / done_pages * (total_pages - done_pages) if done_pages else 0
        if summary:
            detail = (f"{summary['pages'] or '-'} pages, {summary['ocr_pages']} OCR, {summary['chunks']} chunks, "
                      f"{summary['tables']} tables, review {summary['review_pages']}, missing {summary['missing_pages']}")
        else:
            detail = error
        report(f"[{counts['done'] + counts['failed']}/{len(pending)}] {status.upper()} {doc['doc_id']} "
               f"({seconds:.0f} s): {detail} | elapsed {elapsed / 60:.1f} min, pages {done_pages}/{total_pages}, "
               f"ETA {eta / 60:.0f} min")

    arguments = (str(corpus.root),)
    beater = threading.Thread(target=beat, name="corpus-heartbeat", daemon=True)
    if heartbeat > 0:
        beater.start()
    try:
        if workers <= 1:
            for doc in pending:
                started, began = now(), time.perf_counter()
                active[doc["doc_id"]] = (began, doc["pages"] or 1)
                status, summary, error = _guarded(*arguments, doc, config, fingerprint, ocr, str(models))
                record(doc, status, summary, error, started, time.perf_counter() - began)
        else:
            counts["not_started"] = len(_run_pool(pending, workers, arguments, config, fingerprint, ocr, str(models),
                                                  record, recorded, active, report))
    finally:
        stop.set()
    return counts


def _outcome(future) -> tuple[str, dict[str, Any] | None, str | None] | None:
    """What a finished future holds; None if it holds no result of its own (cancelled or the pool broke under it)."""
    if not future.done() or future.cancelled():
        return None
    error = future.exception()
    if error is None:
        return future.result()
    if isinstance(error, BrokenProcessPool):
        return None
    return "failed", None, f"{type(error).__name__}: {error}"[:1000]


def _run_batch(batch, width, alone, arguments, config, fingerprint, ocr, models, record, recorded, active, report):
    """Run ``batch`` in one pool of ``width`` workers. Returns (ran, unstarted) when a worker died, else ([], []).

    ``ran`` are documents a worker had started (marker present) that never reported; ``unstarted`` never began.
    Documents whose result was already available are recorded as they are, never as failed. With ``alone`` the single
    document that was running is the cause of the death and is recorded as failed.
    """
    started, futures, broken = {}, {}, False
    with ProcessPoolExecutor(max_workers=width, mp_context=multiprocessing.get_context("spawn"),
                             max_tasks_per_child=20) as pool:
        for doc in batch:
            started[doc["doc_id"]] = (now(), time.perf_counter())
            futures[pool.submit(_guarded, *arguments, doc, config, fingerprint, ocr, models)] = doc
        try:
            waiting = set(futures)
            while waiting:
                finished, waiting = wait(waiting, timeout=5, return_when=FIRST_COMPLETED)
                for future in waiting:
                    doc = futures[future]
                    if future.running() and doc["doc_id"] not in active:
                        active[doc["doc_id"]] = (time.perf_counter(), doc["pages"] or 1)
                for future in finished:
                    doc = futures[future]
                    try:
                        status, summary, error = future.result()
                    except BrokenProcessPool:
                        raise
                    except Exception as failure:  # for example a result that cannot be sent back: this document only
                        status, summary, error = "failed", None, f"{type(failure).__name__}: {failure}"[:1000]
                    record(doc, status, summary, error, started[doc["doc_id"]][0],
                           time.perf_counter() - active.get(doc["doc_id"], (started[doc["doc_id"]][1], 0))[0])
        except BrokenProcessPool:
            broken = True
    if not broken:
        return [], []
    # Classified after the pool has shut down: its workers are gone, so the markers no longer change.
    corpus = Corpus(Path(arguments[0]))
    ran, unstarted = [], []
    for future, doc in futures.items():
        doc_id = doc["doc_id"]
        if doc_id in recorded:
            continue
        active.pop(doc_id, None)
        elapsed = time.perf_counter() - started[doc_id][1]
        outcome = _outcome(future)
        directory = output_directory(corpus, doc_id, fingerprint)
        if outcome is not None:
            record(doc, *outcome, started[doc_id][0], elapsed)
        elif is_complete(directory):  # the worker finished writing; only its report was lost
            record(doc, "done", completed_summary(directory), None, started[doc_id][0], elapsed)
            clear_marker(directory)
        elif read_marker(directory) is None:
            unstarted.append(doc)
        elif alone:
            clear_marker(directory)
            record(doc, "failed", None, "worker process died while this document ran alone (possibly out of memory)",
                   started[doc_id][0], elapsed)
        else:
            write_marker(directory, doc_id, fingerprint, "interrupted")
            report(f"INTERRUPTED {doc_id}: a worker died while it was running; it is run again alone")
            ran.append(doc)
    return ran, unstarted


def _run_pool(pending, workers, arguments, config, fingerprint, ocr, models, record, recorded, active,
              report=print) -> list[str]:
    """Process ``pending`` with worker processes and survive worker deaths.

    When a worker dies the pool breaks and every worker stops. Documents that had not begun are queued again in a
    new pool. Documents that were running are re-run one at a time: a document that kills a worker even when it runs
    alone is recorded as failed, the others (killed only because the pool broke) are processed normally. A pool that
    dies before any document started is not retried. Returns the doc ids left ``not_started``.
    """
    left: list[str] = []
    queue, suspects = list(pending), []
    while queue or suspects:
        alone = not queue
        batch = [suspects.pop(0)] if alone else queue
        before = len(recorded)
        ran, unstarted = _run_batch(batch, 1 if alone else workers, alone, arguments, config, fingerprint, ocr,
                                    models, record, recorded, active, report)
        suspects.extend(ran)
        if alone:
            left.extend(doc["doc_id"] for doc in unstarted)
            queue = []
        elif unstarted and (ran or len(recorded) > before):
            queue = unstarted
        else:  # nothing ran and nothing finished: a new pool would die the same way
            left.extend(doc["doc_id"] for doc in unstarted)
            queue = []
    return left
