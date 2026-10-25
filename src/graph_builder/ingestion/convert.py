"""Convert verified PDF sources locally with explicit Docling options and cache complete document exports."""
from __future__ import annotations

import logging
import json
from importlib.metadata import PackageNotFoundError, version
import os
from pathlib import Path
import time
from typing import Any

os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["DO_NOT_TRACK"] = "1"

from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
from docling.document_converter import DocumentConverter, PdfFormatOption

from .sources import verify_file, write_json, write_text, sha256

LOGGER = logging.getLogger(__name__)


def make_converter(options: dict[str, Any], ocr_models: Path | None = None) -> DocumentConverter:
    settings = PdfPipelineOptions()
    settings.do_ocr = options["do_ocr"]
    if settings.do_ocr:
        if ocr_models is None:
            raise ValueError("OCR requires a local model directory")
        if not ocr_models.is_dir() or not any(ocr_models.glob("*.pth")):
            raise ValueError(f"OCR model files are missing from {ocr_models}; prefetch EasyOCR models before running offline")
        from importlib.util import find_spec
        if find_spec("easyocr") is None:
            raise ValueError('OCR requires the optional dependencies: pip install -e ".[ocr]"')
        from docling.datamodel.pipeline_options import EasyOcrOptions
        from .ocr_settings import ocr_settings
        ocr = ocr_settings(options)
        settings.ocr_options = EasyOcrOptions(lang=ocr["languages"], use_gpu=False,
                                             force_full_page_ocr=ocr["mode"] == "full_page",
                                             confidence_threshold=ocr["confidence_threshold"],
                                             model_storage_directory=str(ocr_models), download_enabled=False)
    settings.do_table_structure = options["do_table_structure"]
    settings.table_structure_options.mode = TableFormerMode(options["table_mode"])
    settings.table_structure_options.do_cell_matching = options["do_cell_matching"]
    settings.accelerator_options = AcceleratorOptions(device=AcceleratorDevice(options["device"]))
    settings.enable_remote_services = False
    return DocumentConverter(allowed_formats=[InputFormat.PDF], format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=settings)})


def convert_sources(registry: list[dict[str, Any]], root: Path, options: dict[str, Any],
                    cache: Path | None = None, reuse_cache: bool = False) -> list[dict[str, Any]]:
    converter = None
    cache = cache or root / "data" / "interim" / "docling"
    cache.mkdir(parents=True, exist_ok=True)
    timings = []
    from .ocr_settings import ocr_settings
    fingerprint = {"parser": version("docling"), "core": version("docling-core"),
                   "settings": {key: options[key] for key in
                                ("do_ocr", "do_table_structure", "table_mode", "do_cell_matching", "device")}}
    if options["do_ocr"]:
        try:
            fingerprint["easyocr"] = version("easyocr")
        except PackageNotFoundError as error:
            raise ValueError('OCR requires the optional dependencies: pip install -e ".[ocr]"') from error
        fingerprint["ocr"] = ocr_settings(options)
        fingerprint["models"] = {p.name: sha256(p) for p in sorted((root / "data/interim/ocr_models").glob("*.pth"))}
    for source in registry:
        doc_id = source["doc_id"]
        pdf = root / "data" / "raw" / f"{doc_id}.pdf"
        verify_file(pdf, source)
        manifest = cache / f"{doc_id}.cache.json"
        expected = {**fingerprint, "source_sha256": source["sha256"]}
        json_path, markdown_path = cache / f"{doc_id}.json", cache / f"{doc_id}.md"
        if reuse_cache and manifest.exists() and json_path.exists() and markdown_path.exists():
            try:
                saved = json.loads(manifest.read_text(encoding="utf-8"))
                if (isinstance(saved, dict) and saved.get("fingerprint") == expected
                        and saved.get("json_sha256") == sha256(json_path)
                        and saved.get("markdown_sha256") == sha256(markdown_path)):
                    LOGGER.info("Reusing verified conversion cache for %s", doc_id)
                    continue
            except (ValueError, OSError):
                LOGGER.warning("Rebuilding invalid conversion cache for %s", doc_id)
        if converter is None:
            converter = make_converter(options, root / "data/interim/ocr_models" if options["do_ocr"] else None)
        LOGGER.info("Converting %s on CPU", doc_id)
        started = time.perf_counter()
        result = converter.convert(pdf)
        seconds = round(time.perf_counter() - started, 3)
        if result.status.value != "success":
            raise RuntimeError(f"Conversion failed for {doc_id}: {result.status}; {result.errors}")
        write_json(cache / f"{doc_id}.json", result.document.export_to_dict())
        write_text(cache / f"{doc_id}.md", result.document.export_to_markdown())
        write_json(manifest, {"fingerprint": expected, "json_sha256": sha256(json_path),
                              "markdown_sha256": sha256(markdown_path)})
        timings.append({"doc_id": doc_id, "docling_seconds": seconds})
        write_json(root / "data" / "interim" / "run_log.json", {"conversion": timings})
        LOGGER.info("Converted %s in %.3f seconds", doc_id, seconds)
    return timings
