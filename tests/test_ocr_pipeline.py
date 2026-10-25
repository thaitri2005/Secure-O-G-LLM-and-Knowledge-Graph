"""Exercise OCR orchestration/provenance with a controlled converter, not model accuracy."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PIL import Image
from graph_builder.ingestion.__main__ import main
from graph_builder.ingestion.register import register_pdf
from graph_builder.ingestion.sources import load_options, write_json
from graph_builder.ingestion.runs import conversion_cache
from test_chunking import make_document, add_text


class OcrPipelineTests(unittest.TestCase):
    def test_missing_scanned_page_fails_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); (root / "pyproject.toml").touch()
            pdf = root / "scan.pdf"
            page = Image.new("RGB", (600, 1000), "white")
            page.save(pdf, resolution=72, save_all=True, append_images=[page])
            registry = root / "sources.json"
            register_pdf(pdf, registry, "sample", "Two-page scan")
            config = root / "configs/ingestion/vi.json"
            write_json(config, load_options(Path("configs/ingestion/vietnamese.json")))
            document = make_document(2)
            add_text(document, "Only the first page was recognized. The second scanned page is missing entirely.")
            converter = SimpleNamespace(convert=lambda _: SimpleNamespace(
                status=SimpleNamespace(value="success"), document=document))
            args = ["ingestion", "run", "--sources", str(registry), "--config", str(config), "--run-name", "missing"]
            with patch("sys.argv", args), patch("graph_builder.ingestion.convert.make_converter", return_value=converter), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(), 1)
                self.assertIn("scanned page 2", output.getvalue())

    def test_named_local_run_preserves_vietnamese_and_rebuilds_corrupt_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); (root / "pyproject.toml").touch()
            pdf = root / "scan.pdf"
            Image.new("RGB", (600, 1000), "white").save(pdf, resolution=72)
            registry = root / "sources.json"
            register_pdf(pdf, registry, "sample", "Báo cáo kỹ thuật")
            config = root / "configs/ingestion/vi.json"
            options = load_options(Path("configs/ingestion/vietnamese.json"))
            write_json(config, options)
            document = make_document(1)
            text = "Báo cáo kỹ thuật tiếng Việt: nhiệt độ 35°C, áp suất 12 bar và độ sâu 1.955 m."
            add_text(document, text)
            result = SimpleNamespace(status=SimpleNamespace(value="success"), document=document)
            converter = SimpleNamespace(convert=lambda _: result)
            args = ["ingestion", "run", "--sources", str(registry), "--config", str(config), "--run-name", "vi"]
            with patch("graph_builder.ingestion.convert.make_converter", return_value=converter) as factory:
                for _ in range(2):
                    with patch("sys.argv", args), redirect_stdout(io.StringIO()):
                        self.assertEqual(main(), 0)
                self.assertEqual(factory.call_count, 1)
                factory.assert_called_with(options, root / "data/interim/ocr_models")
                cache = conversion_cache(root, options)
                (cache / "sample.json").write_text("corrupt", encoding="utf-8")
                with patch("sys.argv", args), redirect_stdout(io.StringIO()):
                    self.assertEqual(main(), 0)
                self.assertEqual(factory.call_count, 2)
                # Valid JSON of the wrong shape is still a corrupt manifest.
                (cache / "sample.cache.json").write_text("[]", encoding="utf-8")
                with patch("sys.argv", args), redirect_stdout(io.StringIO()):
                    self.assertEqual(main(), 0)
                self.assertEqual(factory.call_count, 3)
            output = root / "data/interim/runs/vi/documents"
            self.assertEqual((output / "sample.txt").read_text(encoding="utf-8"), text)
            record = json.loads((output / "sample.json").read_text(encoding="utf-8"))
            self.assertEqual(record["ocr"]["settings"]["languages"], ["vi", "en"])
            self.assertEqual(record["ocr"]["pages"][0]["status"], "covered")
            self.assertTrue(record["pages"]["1"]["needs_ocr"])

    def test_unnamed_ocr_rejected_before_fetch(self):
        args = ["ingestion", "run", "--config", "configs/ingestion/vietnamese.json"]
        with patch("sys.argv", args), patch("graph_builder.ingestion.__main__.fetch_sources") as fetch, redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 1)
            fetch.assert_not_called()
