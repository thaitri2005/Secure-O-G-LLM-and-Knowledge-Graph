"""Test sentence packing boundaries, whitespace handling, and preservation of source characters."""
from __future__ import annotations

import re
import unittest

from graph_builder.ingestion.text_packing import chunk_spans, split_sentences


class TextPackingTests(unittest.TestCase):
    def test_preserves_characters_and_bounds(self) -> None:
        samples = ["", "  \n\t ", "Alpha. Beta! Gamma? Delta.", "Longwordwithoutspaces" * 8,
                   "First line.\nSecond line has a longer sentence with words.\r\nLast.", "測定値 café 123. End."]
        for text in samples:
            for limit in (1, 7, 25, 100):
                with self.subTest(text=text, limit=limit):
                    spans = chunk_spans(text, limit)
                    self.assertTrue(all(0 < end - start <= limit for start, end in spans))
                    self.assertTrue(all(spans[i][1] <= spans[i + 1][0] for i in range(len(spans) - 1)))
                    actual = re.sub(r"\s+", "", "".join(text[start:end] for start, end in spans))
                    self.assertEqual(actual, re.sub(r"\s+", "", text))

    def test_packs_complete_sentences(self) -> None:
        text = "Alpha. Beta. Gamma."
        self.assertEqual([text[a:b] for a, b in chunk_spans(text, 12)], ["Alpha. Beta.", "Gamma."])

    def test_sentence_base_offset(self) -> None:
        self.assertEqual(split_sentences(" Alpha. Beta. ", base=10), [(11, 17), (18, 23)])

    def test_rejects_nonpositive_limit(self) -> None:
        for limit in (0, -1):
            with self.assertRaises(ValueError):
                chunk_spans("Text", limit)
