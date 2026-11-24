from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pymupdf
from docling.datamodel.base_models import ConversionStatus
from docling.models.postprocessing.list_marker_processor import ListItemMarkerProcessor

from graph_builder.corpus import process
from graph_builder.corpus.catalog import Corpus
from graph_builder.corpus.chunking import chunk_document, restore_list_markers
from graph_builder.corpus.config import fingerprint, load_config, validate_config
from graph_builder.corpus.k1_config import load_k1_config
from graph_builder.corpus.k1_export import export_k1
from graph_builder.corpus.k1_validate import validate_k1
from graph_builder.corpus.qa import fidelity
from test_chunking import add_text, make_document, provenance


class ListMarkerTests(unittest.TestCase):
    def test_k1_keeps_source_numbers_and_qa_confirms_recall(self):
        lines = ["16.3 Casing design", "16.4 Cement program", "16.5 Mud program", "7. Final inspection"]
        document = make_document(pages=1)
        parent = document.add_list_group()
        processor = ListItemMarkerProcessor()
        for index, line in enumerate(lines):
            top = 300 + index * 20
            item = document.add_list_item(text=line, parent=parent, prov=provenance(1, line, top, top + 10))
            processor.process_list_item(item)
        self.assertEqual([item.marker for item in document.texts], ["16.3", "16.4", "16.5", "7."])
        result = SimpleNamespace(status=ConversionStatus.SUCCESS, document=document, confidence=None, errors=[])
        ocr = {"settings": {"engine": "rapidocr"}, "runtime": {}, "models": {}}
        qa_config = fidelity.load_config()
        fingerprints = []
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "sample.pdf"
            with pymupdf.open() as pdf:
                page = pdf.new_page(width=600, height=1000)
                for index, line in enumerate(lines):
                    page.insert_text((100, 310 + index * 20), line)
                pdf.save(source)
            reference = fidelity.PdfReference(source, qa_config)
            try:
                reference_text, _, _ = reference.page_text(1)
                self.assertEqual(reference_text.splitlines(), lines)
            finally:
                reference.close()
            for enabled in (False, True):
                with self.subTest(enabled=enabled):
                    config = load_config(Path("configs/corpus/default.json"))
                    if enabled:
                        config["chunking"]["preserve_list_markers"] = True
                    corpus = Corpus.create(root / str(enabled), validate_config(config))
                    status, _ = corpus.add_file(source)
                    self.assertEqual(status, "added")
                    with patch("graph_builder.corpus.ocr_engines.engine_fingerprint", return_value=ocr), \
                         patch.object(process, "converter", return_value=SimpleNamespace(convert=lambda *a, **k: result)):
                        self.assertEqual(process.run(corpus, root)["done"], 1)
                        release = Path(export_k1(corpus, "sample", root, load_k1_config())["export"])
                    self.assertEqual(validate_k1(release), [])
                    file = next(fidelity.iter_jsonl(release / "files.jsonl"))
                    texts, _ = fidelity.k1_page_texts(release, file["file_id"])
                    items = fidelity.enumerator_items(reference_text, qa_config)
                    comparison = fidelity.compare_page(reference_text, texts[1], "", "", qa_config, enumerator_items=items)
                    self.assertEqual(comparison["numeric"]["recall_raw"], 1.0 if enabled else 0.0)
                    self.assertEqual(comparison["word"]["recall_raw"], 1.0)
                    self.assertEqual(comparison["novel_numeric"], [])
                    codes = dict(fidelity.judge(comparison, "text", False, qa_config))
                    self.assertEqual(fidelity.MARKER_CODE in codes, not enabled)
                    if enabled:
                        self.assertEqual([line for line in texts[1].splitlines() if line], lines)
                    fingerprints.append(fingerprint(config, {}))
        self.assertEqual(len(set(fingerprints)), 2)

    def test_restore_uses_original_text_and_skips_ambiguous_provenance(self):
        document = make_document()
        parent = document.add_list_group()
        for marker, body, original in [("1.", "Already present", "1. Already present"),
                                       ("2.", "2. Kept", "2. Kept"),
                                       ("3.", "Synthesized", "Synthesized"),
                                       ("4.", "Corrected text", "4. Different text"),
                                       ("5.", "Spans pages", "5. Spans pages")]:
            document.add_list_item(text=body, marker=marker, orig=original, parent=parent,
                                   prov=provenance(1, body))
        document.texts[-1].prov.append(provenance(2, "pages"))
        restore_list_markers(document)
        restore_list_markers(document)
        self.assertEqual([item.text for item in document.texts],
                         ["1. Already present", "2. Kept", "Synthesized", "Corrected text", "Spans pages"])

    def test_chunk_budget_keeps_marker_with_its_first_word(self):
        config = load_config(Path("configs/corpus/default.json"))
        config["chunking"].update(max_chars=200, preserve_list_markers=True)
        document = make_document(pages=1)
        add_text(document, "a" * 196)
        parent = document.add_list_group()
        document.add_list_item(text="Inspect casing.", marker="7.", orig="7. Inspect casing.",
                               parent=parent, prov=provenance(1, "7. Inspect casing.", 400, 410))
        restore_list_markers(document)
        chunks, _, _ = chunk_document(document, "sample", config, set())
        self.assertEqual([chunk["text"] for chunk in chunks], ["a" * 196, "7. Inspect casing."])
