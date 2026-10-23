"""Verify portfolio child identity, integrity and parent attribution."""
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from pypdf import PdfWriter
from graph_builder.ingestion.portfolio import expand_portfolios, split_portfolio


class PortfolioTests(unittest.TestCase):
    def test_portfolio_children_are_pinned_and_safe(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "data/raw"
            raw.mkdir(parents=True)
            child = PdfWriter()
            child.add_blank_page(width=100, height=100)
            stream = io.BytesIO()
            child.write(stream)
            portfolio = PdfWriter()
            portfolio.add_blank_page(width=100, height=100)
            portfolio.add_attachment("../Measurements.pdf", stream.getvalue())
            portfolio.add_attachment("Duplicate.pdf", stream.getvalue())
            pdf = raw / "sample_appendices.pdf"
            portfolio.write(pdf)
            source = {"doc_id": "sample_appendices", "bytes": pdf.stat().st_size,
                      "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(), "portfolio": True}
            children = expand_portfolios([source], root)
            self.assertEqual(len(children), 1)
            self.assertEqual(children[0]["doc_id"], "sample_appx_01_measurements")
            self.assertEqual(children[0]["parent_doc_id"], source["doc_id"])
            self.assertEqual(split_portfolio(source, root), children)
            self.assertEqual(expand_portfolios([children[0]], root), children)
            (raw / (children[0]["doc_id"] + ".pdf")).write_bytes(b"changed")
            with self.assertRaises(ValueError):
                split_portfolio(source, root)
