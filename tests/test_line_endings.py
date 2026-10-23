"""Exercise every run/publish text artifact and older CRLF publication inputs."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pypdf import PdfWriter

from graph_builder.ingestion.__main__ import main
from graph_builder.ingestion.sources import load_options, sha256, write_checksums, write_json, write_text
from test_chunking import add_table, add_text, make_document


class LineEndingTests(unittest.TestCase):
    def test_checksums_cover_only_the_registry_and_are_sorted(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            names = ["documents/a.json", "documents/a.txt", "gdr_chunks.json", "gdr_chunks_full.jsonl", "gdr_tables.jsonl"]
            for name in names:
                write_text(directory / name, "Bundle\n")
            write_text(directory / "local/secondary/SHA256SUMS", "Local\n")
            write_text(directory / "documents/other.txt", "Other document\n")
            write_checksums(directory, ["a"])
            expected = "".join(f"{sha256(directory / name)}  {name}\n" for name in names)
            self.assertEqual((directory / "SHA256SUMS").read_bytes(), expected.encode())
            write_checksums(directory, ["a"])
            self.assertEqual((directory / "SHA256SUMS").read_bytes(), expected.encode())
    def test_text_writer_normalizes_existing_line_endings(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "nested/passage.txt"
            write_text(path, "First\r\nSecond\rThird\n")
            self.assertEqual(path.read_bytes(), b"First\nSecond\nThird\n")

    def test_run_and_publish_write_only_lf(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").touch()
            pdf = root / "data/raw/sample.pdf"
            pdf.parent.mkdir(parents=True)
            writer = PdfWriter()
            writer.add_blank_page(width=600, height=1000)
            writer.write(pdf)
            document = make_document(1)
            passage = add_text(document, "A source passage. Another sentence.")
            passage.prov[0].bbox.l = 100.1211
            add_table(document, rows=5)
            source = {"doc_id": "sample", "title": "Example", "well": "Example",
                      "url": "https://gdr.openei.org/example.pdf",
                      "landing_page": "https://gdr.openei.org/submissions/1", "gdr_submission": 1,
                      "license": {"id": "CC-BY-4.0", "url": "https://creativecommons.org/licenses/by/4.0/"},
                      "sha256": sha256(pdf), "bytes": pdf.stat().st_size}
            config = root / "configs/ingestion/default.json"
            options = load_options(Path("configs/ingestion/default.json"))
            options["spot_checks"] = []
            write_json(config, options)
            registry = root / "configs/sources/gdr_end_of_well.json"
            write_json(registry, [source])
            result = SimpleNamespace(status=SimpleNamespace(value="success"), document=document)
            converter = SimpleNamespace(convert=lambda _: result)
            args = ["ingestion", "run", "--sources", str(registry), "--config", str(config), "--run-name", "sample"]
            with patch("sys.argv", args), patch("graph_builder.ingestion.convert.make_converter", return_value=converter), redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 0)
            for path in (root / "data").rglob("*"):
                if path.is_file() and path.suffix != ".pdf":
                    self.assertNotIn(b"\r\n", path.read_bytes(), str(path.relative_to(root)))
            directory = root / "data/interim/runs/sample"
            sidecar = directory / "gdr_chunks_full.jsonl"
            records = [json.loads(line) for line in sidecar.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(records[0]["regions"][0]["bbox"][0], 100.12)
            records[0]["regions"][0]["bbox"][0] += .0001
            write_text(sidecar, "".join(json.dumps(record) + "\n" for record in records))
            write_json(directory / "metrics.json", {"validated": True, "sha256": sha256(directory / "gdr_chunks.json")})
            # Simulate sidecars/documents written by an older Windows script.
            for path in [directory / "gdr_chunks_full.jsonl", directory / "gdr_tables.jsonl", *(directory / "documents").iterdir()]:
                path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
            args[1:] = ["publish", "--sources", str(registry), "--config", str(config), "--run", "sample"]
            with patch("sys.argv", args), redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 0)
            for path in (root / "data/processed").rglob("*"):
                if path.is_file():
                    self.assertNotIn(b"\r\n", path.read_bytes(), str(path.relative_to(root)))
            self.assertTrue((root / "data/processed/SHA256SUMS").exists())
            published = json.loads((root / "data/processed/gdr_chunks_full.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(published["regions"][0]["bbox"][0], 100.12)
            main_bytes = {path: path.read_bytes() for path in (root / "data/processed").rglob("*") if path.is_file()}
            # Use the same synthetic source as a secondary registry in this repository.
            registry.unlink()
            registry = registry.with_name("secondary.json")
            write_json(registry, [source])
            args[1:] = ["publish", "--sources", str(registry), "--config", str(config), "--run", "sample"]
            with patch("sys.argv", args), redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 0)
            secondary = root / "data/processed/local/secondary"
            self.assertEqual((secondary / "gdr_chunks.json").read_bytes(), (directory / "gdr_chunks.json").read_bytes())
            self.assertEqual((secondary / "SHA256SUMS").read_bytes(), (root / "data/processed/SHA256SUMS").read_bytes())
            args[1:] = ["run", "--sources", str(registry), "--config", str(config)]
            with patch("sys.argv", args), patch("graph_builder.ingestion.convert.make_converter", return_value=converter), redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 0)
            for path, original in main_bytes.items():
                self.assertEqual(path.read_bytes(), original)
            for path in secondary.rglob("*"):
                if path.is_file():
                    self.assertNotIn(b"\r\n", path.read_bytes())
