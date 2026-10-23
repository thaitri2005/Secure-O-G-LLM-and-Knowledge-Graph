"""Test constrained page continuation and hybrid source spans."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from docling_core.types.doc import DocItemLabel
from graph_builder.ingestion.chunking import chunks_from_document
from graph_builder.ingestion.sources import load_options
from graph_builder.ingestion.strategies import hybrid_chunks, PassageSerializerProvider
from test_chunking import make_document, add_text, add_table


class StrategyTests(unittest.TestCase):
    def test_hybrid_serializer_preserves_table_format(self):
        document = make_document()
        add_table(document)
        rendered = PassageSerializerProvider().get_serializer(document).serialize().text
        self.assertIn("|", rendered)
        self.assertNotIn(" = ", rendered)

    def test_paragraph_continuation_requires_all_conditions(self):
        for previous, following, count in (("Continues", "on next page.", 1), ("Ends.", "next page.", 2),
                                            ("Continues", "New sentence.", 2), ("Depth", "100 feet.", 1)):
            doc = make_document()
            add_text(doc, previous)
            add_text(doc, following, page=2)
            metadata = []
            chunks, _ = chunks_from_document(doc, "sample", 1500, .08, .5, 1, .5, 3, metadata, "paragraph")
            self.assertEqual(len(chunks), count)
            if count == 1:
                self.assertEqual(chunks[0]["page"], 1)
                self.assertEqual({r["page"] for r in metadata[0]["regions"]}, {1, 2})
        doc = make_document()
        add_text(doc, "Continues")
        add_text(doc, "New section", page=2, label=DocItemLabel.SECTION_HEADER)
        add_text(doc, "lowercase start.", page=2)
        chunks, _ = chunks_from_document(doc, "sample", 1500, .08, .5, 1, .5, 3, strategy="paragraph")
        self.assertEqual(len(chunks), 2)

    def test_hybrid_uses_first_item_and_full_regions(self):
        doc = make_document()
        first = add_text(doc, "First")
        second = add_text(doc, "second", page=2)
        class Chunker:
            def chunk(self, document):
                return [SimpleNamespace(text="First second", meta=SimpleNamespace(doc_items=[first, second], headings=["Section"]))]
        chunks, metadata = hybrid_chunks(doc, "sample", load_options(Path("configs/ingestion/default.json")), Chunker())
        self.assertEqual(chunks[0]["page"], 1)
        self.assertEqual(chunks[0]["text"], "First second")
        self.assertEqual(len(metadata[0]["regions"]), 2)
