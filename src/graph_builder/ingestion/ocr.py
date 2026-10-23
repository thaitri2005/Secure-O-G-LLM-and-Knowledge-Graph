"""Measure appendix-only OCR trials without changing text-layer deliverables."""
from pathlib import Path
import json
from docling_core.types.doc import DoclingDocument
from pypdf import PdfReader, PdfWriter
from .sources import write_json


def trial_ocr(root: Path, source: dict, marked: list[int], options: dict, converter=None) -> list[dict]:
    if not source.get("parent_doc_id"):
        raise ValueError("OCR trials are restricted to appendix children")
    directory = root / "data/interim/ocr" / source["doc_id"]
    directory.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(root / "data/raw" / f"{source['doc_id']}.pdf")
    report = []
    for number in marked:
        cached = directory / f"page_{number}.json"
        if not cached.exists():
            pdf = directory / f"page_{number}.pdf"
            writer = PdfWriter()
            writer.add_page(reader.pages[number - 1])
            writer.write(pdf)
            if converter is None:
                from .convert import make_converter
                converter = make_converter({**options, "do_ocr": True}, root / "data/interim/ocr_models")
            result = converter.convert(pdf)
            if result.status.value != "success":
                raise RuntimeError(f"OCR trial conversion failed for page {number}")
            write_json(cached, result.document.export_to_dict())
        document = DoclingDocument.model_validate_json(cached.read_text(encoding="utf-8"))
        text = " ".join([item.text for item in document.texts]
                        + [cell.text for table in document.tables for cell in table.data.table_cells])
        report.append({"doc_id": source["doc_id"], "page": number,
                       "text_layer_words": len((reader.pages[number - 1].extract_text() or "").split()),
                       "ocr_words": len(text.split())})
        write_json(directory / "metrics.json", report)
    return report


def evaluate_ocr(root: Path, name: str) -> dict:
    """Run the optional trial on computed scanned pages of an appendix run."""
    from .runs import run_directory
    directory = run_directory(root, name)
    sources = json.loads((directory / "sources.json").read_text(encoding="utf-8"))
    if any(not source.get("parent_doc_id") for source in sources):
        raise ValueError("OCR trials are restricted to appendix children")
    options = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    pages = []
    for source in sources:
        document = json.loads((directory / "documents" / f"{source['doc_id']}.json").read_text(encoding="utf-8"))
        marked = [int(number) for number, page in document["pages"].items() if page["needs_ocr"]]
        pages.extend(trial_ocr(root, source, marked, options))
    result = {"scanned_pages": len(pages), "text_layer_words": sum(p["text_layer_words"] for p in pages),
              "ocr_words": sum(p["ocr_words"] for p in pages), "pages": pages}
    write_json(root / "data/interim/ocr/metrics.json", result)
    return {key: value for key, value in result.items() if key != "pages"}
