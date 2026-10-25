"""Local PDFs use the same integrity and staging guarantees as remote inputs."""
import json
from pathlib import Path
import tempfile
import unittest
from pypdf import PdfWriter
from graph_builder.ingestion.sources import load_registry, fetch_sources, sha256, write_json


class LocalSourceTests(unittest.TestCase):
    def test_invalid_registry_values_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            registry = Path(temporary) / "sources.json"
            source = {"doc_id": "sample", "title": "Report", "path": "report.pdf",
                      "license": {"id": "private", "url": ""}, "bytes": 10, "sha256": "a" * 64}
            for change in ({"sha256": None}, {"title": []}, {"license": {"id": "", "url": ""}}):
                with self.subTest(change=change):
                    write_json(registry, [{**source, **change}])
                    with self.assertRaises(ValueError):
                        load_registry(registry)

    def test_registration_preserves_malformed_registry(self):
        from graph_builder.ingestion.register import register_pdf
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf, registry = root / "sample.pdf", root / "sources.json"
            writer = PdfWriter(); writer.add_blank_page(width=600, height=800); writer.write(pdf)
            write_json(registry, [None])
            original = registry.read_bytes()
            with self.assertRaises(ValueError):
                register_pdf(pdf, registry, "sample", "Report")
            self.assertEqual(registry.read_bytes(), original)

    def test_registration_limits_and_duplicate_protection(self):
        from graph_builder.ingestion.register import register_pdf
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); pdf = root / "report.pdf"; registry = root / "sources.json"
            writer = PdfWriter(); writer.add_blank_page(width=600, height=800); writer.write(pdf)
            register_pdf(pdf, registry, "sample", "Báo cáo")
            original = registry.read_bytes()
            with self.assertRaisesRegex(ValueError, "duplicate"):
                register_pdf(pdf, registry, "sample", "Again")
            self.assertEqual(original, registry.read_bytes())
            pdf.write_bytes(b"not a PDF")
            with self.assertRaisesRegex(ValueError, "signature"):
                register_pdf(pdf, registry, "bad", "Invalid")

    def test_local_import_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf = root / "report.pdf"
            writer = PdfWriter(); writer.add_blank_page(width=600, height=800); writer.write(pdf)
            registry = root / "sources.json"
            write_json(registry, [{"doc_id": "vietnamese", "title": "Báo cáo", "path": "report.pdf",
                                  "license": {"id": "private", "url": ""},
                                  "bytes": pdf.stat().st_size, "sha256": sha256(pdf)}])
            sources = load_registry(registry)
            self.assertIsNone(sources[0]["gdr_submission"])
            self.assertFalse(fetch_sources(sources, root)[0]["cached"])
            self.assertTrue(fetch_sources(sources, root)[0]["cached"])
            self.assertEqual((root / "data/raw/vietnamese.pdf").read_bytes(), pdf.read_bytes())
            (root / "data/raw/vietnamese.pdf").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "mismatch"):
                fetch_sources(sources, root)
