"""Check metric denominators, numeric normalization and source exclusions."""
from pathlib import Path
import tempfile
import unittest

from docling_core.types.doc import DocItemLabel

from graph_builder.ingestion.evaluation import evaluate_run, exclusion_regions, fidelity, naive_chunks, normalize_numbers, quantities, reference_text, repeated_lines, tokens
from graph_builder.ingestion.sources import load_options, write_json
from graph_builder.ingestion.runs import prepare_run
from graph_builder.ingestion.chunking import chunk_documents
from pypdf import PdfWriter
from test_chunking import add_text, make_document


class EvaluationTests(unittest.TestCase):
    def test_complete_metrics(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf = root / "data/raw/sample.pdf"
            pdf.parent.mkdir(parents=True)
            writer = PdfWriter()
            writer.add_blank_page(width=600, height=1000)
            writer.write(pdf)
            doc = make_document(1)
            add_text(doc, "A passage.")
            write_json(root / "data/interim/docling/sample.json", doc.export_to_dict())
            options = load_options(Path("configs/ingestion/default.json"))
            options["table_mode"] = "accurate"
            directory = prepare_run(root, "sample", options, [{"doc_id": "sample"}])
            chunk_documents([{"doc_id": "sample"}], root, options, output=directory / "gdr_chunks.json")
            measured = evaluate_run(root, "sample")
            self.assertTrue(measured["deterministic"])
            self.assertEqual(measured["short_text_chunks"], 1)
            self.assertIsNone(measured["quantity_recall"])
            self.assertEqual(naive_chunks([{"doc_id": "sample"}], root, 1500), [])
    def test_numbers_and_units(self):
        self.assertEqual(normalize_numbers("1 , 95 5 ft"), "1955 ft")
        self.assertEqual(quantities("1,955 ft; 12 psi; 10%; 8 lb/ft; 2 in; 4'"),
                         {"1955ft", "12psi", "10%", "8lb/ft", "2in", "4'"})
        self.assertEqual(tokens("A_b, 1,000 ft"), {"a", "b", "1000", "ft"})

    def test_fidelity_counts_missing_and_added_words(self):
        measured = fidelity("Well 10 ft deep", "Well 12 ft deep extra")
        self.assertEqual(measured["word_recall"], .75)
        self.assertEqual(measured["word_precision"], .6)
        self.assertEqual(measured["missed_quantities"], ["10ft"])
        self.assertIsNone(fidelity("", "")["word_recall"])

    def test_regions_and_frequency(self):
        doc = make_document()
        add_text(doc, "Page 1", top=950, bottom=960, label=DocItemLabel.PAGE_FOOTER)
        add_text(doc, "Page 2", page=2, top=950, bottom=960, label=DocItemLabel.PAGE_FOOTER)
        add_text(doc, "Body text.")
        options = load_options(Path("configs/ingestion/default.json"))
        self.assertGreaterEqual(len(exclusion_regions(doc, options)), 2)
        self.assertIn("page #", repeated_lines(doc))

    def test_spatial_reference_excludes_footer_only(self):
        class Page:
            class mediabox:
                height = 1000
            def extract_text(self, visitor_text):
                for text, y in (("Body.", 700), ("Footer", 50)):
                    visitor_text(text, [1, 0, 0, 1, 0, 0], [1, 0, 0, 1, 100, y], None, 10)
        result = reference_text(Page(), [{"bbox": [90, 940, 200, 960]}])
        self.assertEqual(result, "Body.")
        Page.rotation = 90
        result = reference_text(Page(), [{"bbox": [40, 90, 60, 110]}])
        self.assertEqual(result, "Body.")
