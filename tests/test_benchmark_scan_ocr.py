from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.benchmark_scan_ocr import Word, positioned_matches, tesseract_page


class ScanOcrBenchmarkTests(unittest.TestCase):
    def test_tesseract_preserves_literal_quote_without_swallowing_later_rows(self):
        tsv = (
            "level\tleft\ttop\twidth\theight\tconf\ttext\n"
            '5\t1\t2\t10\t9\t100\t"\n'
            "5\t1\t22\t10\t9\t90\t-1.25\n"
        )
        with patch("scripts.benchmark_scan_ocr.subprocess.run", return_value=SimpleNamespace(stdout=tsv)):
            text, words = tesseract_page(Path("sample.png"))
        self.assertEqual(text, ['"', "-1.25"])
        self.assertEqual(words[1], Word("-1.25", (1, 22, 11, 31), 0.90))

    def test_numeric_agreement_checks_location_and_counts_each_occurrence_once(self):
        gold = [Word("12.30", (0, 0, 20, 10)), Word("17.30", (40, 0, 60, 10)),
                Word("12.30", (0, 20, 20, 30))]
        swapped = [Word("17.30", gold[0].box), Word("12.30", gold[1].box)]
        self.assertEqual(positioned_matches(gold, swapped), (set(), set()))
        predicted = [Word("12.30,", gold[0].box), Word("12.30", gold[0].box),
                     Word("12.30", gold[2].box), Word("17.3", gold[1].box)]
        self.assertEqual(positioned_matches(gold, predicted), ({0, 2}, {0, 2}))
