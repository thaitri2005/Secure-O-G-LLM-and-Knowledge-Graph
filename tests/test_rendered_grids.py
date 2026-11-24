from importlib.util import find_spec
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw
import pymupdf

from graph_builder.corpus.complex_grids import independent_words
from graph_builder.corpus.source_grids import repair_document


@unittest.skipUnless(find_spec("cv2"), "rendered ruling detection requires OpenCV")
class RenderedGridTests(unittest.TestCase):
    grid = [["Stage", "Pressure (psi)", "Status"], ["Baseline", "-3.75", "Stable"],
            ["Midpoint", "8.25", "Hold"], ["Final", "15.2", "Confirmed"]]

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.pdf = Path(directory.name) / "rendered-rules.pdf"

    def make_pdf(self, *, missing_divider=False):
        xs = (24, 122, 227, 337)
        ys = (83, 108, 133, 158, 183)
        scale = 3
        image = Image.new("L", (360 * scale, 240 * scale), 255)
        drawing = ImageDraw.Draw(image)
        for y in (62, *ys):
            for x in range(xs[0] * scale, xs[-1] * scale, 5):
                drawing.line((x, y * scale, x + 2, y * scale), fill=80, width=2)
        vertical = (xs[0], *xs[2:]) if missing_divider else xs
        for x in vertical:
            for y in range(ys[0] * scale, ys[-1] * scale, 5):
                drawing.line((x * scale, y, x * scale, y + 2), fill=80, width=2)
        png = BytesIO()
        image.save(png, format="PNG")
        with pymupdf.open() as document:
            page = document.new_page(width=360, height=240)
            page.insert_image(page.rect, stream=png.getvalue())
            for baseline, row in zip((77, 100, 126, 150), self.grid, strict=True):
                for x, value in zip(xs[:-1], row, strict=True):
                    page.insert_text((x + 5, baseline), value, fontsize=10)
            document.save(self.pdf)

    def recover(self):
        return repair_document(self.pdf, [{"page": 1, "mode": "text"}], [], [], "measurements",
                               1500, lambda: self.fail("Expected an unclaimed source region"), allow_complex=True)

    def test_rendered_rules_recover_searchable_cells_and_trim_trailing_blank_row(self):
        self.make_pdf()
        chunks, (table,), (finding,) = self.recover()
        self.assertEqual(table["grid"], self.grid)
        self.assertEqual(finding["structure"], "rendered_rulings")
        self.assertIn("| Baseline | -3.75 | Stable |", chunks[0]["text"])

    def test_missing_divider_does_not_merge_two_headings(self):
        self.make_pdf(missing_divider=True)
        _, tables, _ = self.recover()
        self.assertFalse(tables)

    def test_readers_must_agree_on_printed_value(self):
        self.make_pdf()
        words = [("8.26" if word == "8.25" else word, box) for word, box in independent_words(self.pdf, 1)]
        with patch("graph_builder.corpus.complex_grids.independent_words", return_value=words):
            _, tables, _ = self.recover()
            self.assertFalse(tables)
