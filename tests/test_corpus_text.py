import unittest

from graph_builder.corpus.analysis import PageAnalysis, analysis_config, decide, segments, union_area
from graph_builder.corpus.chunking import language, pack, split_sentences
from graph_builder.corpus.text_metrics import compare
from graph_builder.corpus.vietnamese import is_valid_syllable, text_profile


class VietnameseSpellingTest(unittest.TestCase):
    def test_valid_and_invalid_syllables(self):
        for word in ("Việt", "nghiêng", "quyết", "giữ", "gì", "khuya", "ngoằn", "thác", "dầu", "khí"):
            self.assertTrue(is_valid_syllable(word), word)
        # wrong tone on a -c ending, horn mismatch, legacy-encoded letter, two tones
        for word in ("thàc", "nưóc", "ViÖt", "aáà"):
            self.assertFalse(is_valid_syllable(word), word)

    def test_profile_flags_legacy_encodings_and_ocr_errors(self):
        clean = text_profile("Luật Dầu khí quy định về điều tra cơ bản và hoạt động dầu khí")
        self.assertEqual(clean["invalid_vietnamese"], 0)
        self.assertEqual(clean["foreign_letters"], 0)
        tcvn3 = text_profile("ViÖt Nam, Hµ Néi, tiÕng ViÖt, dÇu khÝ")
        self.assertGreater(tcvn3["foreign_letter_rate"], 0.3)
        ocr = text_profile("nưóc ngoàl nuớc ngoài dầu khí")
        self.assertGreater(ocr["invalid_vietnamese"], 0)

    def test_single_letter_list_markers_are_ignored(self):
        self.assertEqual(text_profile("đ) Quy định khác")["invalid_vietnamese"], 0)


class PagePlanTest(unittest.TestCase):
    def page(self, **values):
        defaults = dict(page=1, width=600, height=800, rotation=0, text_chars=500, image_coverage=0.0,
                        path_objects=0, text_objects=10, invisible_text_objects=0, bad_char_rate=0.0,
                        profile=text_profile("Luật này quy định về điều tra cơ bản về dầu khí " * 5))
        defaults.update(values)
        return decide(PageAnalysis(**defaults), analysis_config(None))

    def test_modes(self):
        self.assertEqual(self.page().mode, "text")
        self.assertEqual(self.page(text_chars=0, image_coverage=0.9).mode, "ocr")
        self.assertEqual(self.page(text_chars=0, path_objects=2000).mode, "ocr")
        self.assertEqual(self.page(text_chars=0).mode, "text")
        self.assertEqual(self.page(image_coverage=0.4).mode, "hybrid")
        garbled = self.page(profile=text_profile("ViÖt Nam Hµ Néi tiÕng ViÖt dÇu khÝ " * 5))
        self.assertEqual(garbled.mode, "ocr")
        self.assertIn("foreign_letters", garbled.reasons)
        hidden = self.page(invisible_text_objects=10, image_coverage=1.0, bad_char_rate=0.5)
        self.assertEqual(hidden.reasons[0], "hidden_text_layer")

    def test_segments_batch_text_and_isolate_ocr_pages(self):
        modes = ["text", "text", "ocr", "ocr", "hybrid", "text", "text", "text"]
        self.assertEqual(segments(modes, 2), [("text", 1, 2), ("ocr", 3, 3), ("ocr", 4, 4), ("hybrid", 5, 5),
                                              ("text", 6, 7), ("text", 8, 8)])

    def test_union_area_counts_overlap_once(self):
        self.assertEqual(union_area([(0, 0, 10, 10), (5, 5, 15, 15)]), 175)


class ChunkTextTest(unittest.TestCase):
    def test_sentence_split_handles_vietnamese_capitals(self):
        text = "Điều 1. Phạm vi điều chỉnh. Đối tượng áp dụng gồm cơ quan. Ưu đãi đầu tư."
        pieces = [text[a:b] for a, b in split_sentences(text)]
        self.assertEqual(pieces[-1], "Ưu đãi đầu tư.")
        self.assertEqual(len(pieces), 4)

    def test_pack_respects_budget_and_offsets(self):
        text = " ".join(f"Câu số {i} nói về giếng khoan." for i in range(40))
        spans = pack(text, 120)
        self.assertTrue(all(end - start <= 120 for start, end in spans))
        self.assertEqual(text[spans[0][0]:spans[0][1]].split()[0], "Câu")

    def test_language(self):
        self.assertEqual(language("Giếng được khoan tới độ sâu 1.955 ft"), "vi")
        self.assertEqual(language("The well was drilled to 1,955 ft"), "en")
        self.assertEqual(language("12 34"), "und")


class TextMetricsTest(unittest.TestCase):
    def test_compare(self):
        result = compare("Luật Dầu khí", "Luật Dầu khi")
        self.assertAlmostEqual(result["cer"], round(1 / 12, 4))
        self.assertEqual(result["word_recall"], round(2 / 3, 4))
        self.assertEqual(compare("a b", "")["word_precision"], None)


if __name__ == "__main__":
    unittest.main()
