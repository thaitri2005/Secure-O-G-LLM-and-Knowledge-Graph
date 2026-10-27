"""Build Docling converters with local-only models, and convert documents in page segments."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("DO_NOT_TRACK", "1")


def build_converter(options: dict[str, Any], models: Path, full_page_ocr: bool | None, threads: int | None = None):
    """Return a Docling converter.

    `full_page_ocr` None disables OCR (text layer only), False OCRs only image regions the text layer does not cover,
    True replaces the text layer with OCR of the whole page.
    """
    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption
    from .ocr_engines import ocr_options

    settings = PdfPipelineOptions()
    settings.do_ocr = full_page_ocr is not None
    if settings.do_ocr:
        settings.ocr_options = ocr_options(models, options["ocr"], full_page=bool(full_page_ocr))
    settings.do_table_structure = True
    settings.table_structure_options.mode = TableFormerMode(options.get("table_mode", "fast"))
    settings.table_structure_options.do_cell_matching = True
    settings.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CPU,
                                                      num_threads=threads or min(8, os.cpu_count() or 4))
    settings.enable_remote_services = False
    settings.document_timeout = options.get("document_timeout")
    formats = {InputFormat.PDF: PdfFormatOption(pipeline_options=settings),
               InputFormat.IMAGE: ImageFormatOption(pipeline_options=settings)}
    return DocumentConverter(allowed_formats=list(formats), format_options=formats)
