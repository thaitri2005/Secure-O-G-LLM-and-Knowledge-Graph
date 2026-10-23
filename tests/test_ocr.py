"""Ensure OCR remains appendix-only and cached trials report actual words."""
from pathlib import Path
import tempfile
import unittest
from pypdf import PdfWriter
from graph_builder.ingestion.ocr import evaluate_ocr, trial_ocr
from graph_builder.ingestion.sources import write_json
from test_chunking import make_document, add_text


class OcrTests(unittest.TestCase):
    def test_cached_trial_and_scope_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(ValueError):
                trial_ocr(root, {"doc_id": "sample"}, [], {})
            source = {"doc_id": "sample", "parent_doc_id": "parent"}
            pdf = root / "data/raw/sample.pdf"
            pdf.parent.mkdir(parents=True)
            writer = PdfWriter()
            writer.add_blank_page(width=600, height=1000)
            writer.write(pdf)
            document = make_document(1)
            add_text(document, "Three recognized words")
            write_json(root / "data/interim/ocr/sample/page_1.json", document.export_to_dict())
            result = trial_ocr(root, source, [1], {})
            self.assertEqual(result[0]["ocr_words"], 3)
            self.assertEqual(result[0]["text_layer_words"], 0)
            directory = root / "data/interim/runs/appendix"
            write_json(directory / "sources.json", [source])
            write_json(directory / "config.json", {})
            write_json(directory / "documents/sample.json", {"pages": {"1": {"needs_ocr": True}}})
            self.assertEqual(evaluate_ocr(root, "appendix"), {"scanned_pages": 1, "text_layer_words": 0, "ocr_words": 3})
