"""Convert verified PDF sources locally with explicit Docling options and cache complete document exports."""
from __future__ import annotations

import logging
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

from .sources import verify_file, write_json, write_text

LOGGER = logging.getLogger(__name__)


def make_converter(options: dict[str, Any], ocr_models: Path | None = None) -> DocumentConverter:
    settings = PdfPipelineOptions()
    settings.do_ocr = options["do_ocr"]
    if settings.do_ocr:
        if ocr_models is None:
            raise ValueError("OCR trials require a local model directory")
        from docling.datamodel.pipeline_options import EasyOcrOptions
        settings.ocr_options = EasyOcrOptions(lang=["en"], use_gpu=False,
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
    for source in registry:
        doc_id = source["doc_id"]
        pdf = root / "data" / "raw" / f"{doc_id}.pdf"
        verify_file(pdf, source)
        if reuse_cache and (cache / f"{doc_id}.json").exists():
            LOGGER.info("Reusing verified conversion cache for %s", doc_id)
            continue
        if converter is None:
            converter = make_converter(options)
        LOGGER.info("Converting %s on CPU", doc_id)
        started = time.perf_counter()
        result = converter.convert(pdf)
        seconds = round(time.perf_counter() - started, 3)
        if result.status.value != "success":
            raise RuntimeError(f"Conversion failed for {doc_id}: {result.status}; {result.errors}")
        write_json(cache / f"{doc_id}.json", result.document.export_to_dict())
        write_text(cache / f"{doc_id}.md", result.document.export_to_markdown())
        timings.append({"doc_id": doc_id, "docling_seconds": seconds})
        write_json(root / "data" / "interim" / "run_log.json", {"conversion": timings})
        LOGGER.info("Converted %s in %.3f seconds", doc_id, seconds)
    return timings
