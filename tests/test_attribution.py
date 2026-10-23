"""Prevent cross-page recall inflation and serializer precision artifacts."""
import unittest
from graph_builder.ingestion.attribution import source_spans, page_texts
from test_chunking import make_document, add_text
from graph_builder.ingestion.chunking import chunks_from_document


class AttributionTests(unittest.TestCase):
    def test_joined_pages_keep_their_own_words_and_quantities(self):
        doc = make_document()
        add_text(doc, "Depth 10 ft continues")
        add_text(doc, "at pressure 20 psi.", page=2)
        metadata = []
        chunks, _ = chunks_from_document(doc, "sample", 1500, .08, .5, 1, .5, 3,
                                         metadata, "paragraph")
        pages = page_texts({**chunks[0], **metadata[0]})
        self.assertIn("10 ft", pages[1])
        self.assertNotIn("20 psi", pages[1])
        self.assertIn("20 psi", pages[2])
        self.assertNotIn("10 ft", pages[2])

    def test_source_charspan_and_added_tokens(self):
        doc = make_document()
        item = add_text(doc, "First page second page")
        item.prov[0].charspan = (0, 10)
        second = item.prov[0].model_copy(deep=True)
        second.page_no, second.charspan = 2, (11, 22)
        item.prov.append(second)
        text = "First page ADDED second page"
        spans = source_spans(doc, text, [(item, None)])
        self.assertEqual(spans[0]["start"], 0)
        self.assertEqual(spans[-1]["end"], len(text))
        pages = page_texts({"text": text, "source_spans": spans})
        self.assertIn("First page", pages[1])
        self.assertIn("second page", pages[2])
        self.assertIn("ADDED", " ".join(pages.values()))

    def test_missing_multi_page_spans_fail(self):
        with self.assertRaises(ValueError):
            page_texts({"text": "passage", "page": 1, "regions": [{"page": 1}, {"page": 2}]})
