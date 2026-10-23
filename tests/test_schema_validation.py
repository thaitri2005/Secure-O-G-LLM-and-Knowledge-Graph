"""Check schemas and cross-file evidence invariants with a synthetic PDF."""
import json
from pathlib import Path
import tempfile
import unittest
from pypdf import PdfWriter

from graph_builder.ingestion.chunking import chunk_documents
from graph_builder.ingestion.schema_validation import validate_artifacts
from graph_builder.ingestion.sources import load_options, write_json
from graph_builder.ingestion.sources import sha256
from graph_builder.ingestion.runs import prepare_run, publish_run
from test_chunking import make_document, add_text, add_table


class ArtifactTests(unittest.TestCase):
    def test_complete_bundle_and_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf = root / "data/raw/sample.pdf"
            pdf.parent.mkdir(parents=True)
            writer = PdfWriter()
            writer.add_blank_page(width=600, height=1000)
            writer.write(pdf)
            doc = make_document(1)
            add_text(doc, "A source passage.")
            add_table(doc, rows=5)
            write_json(root / "data/interim/docling/sample.json", doc.export_to_dict())
            source = {"doc_id": "sample", "title": "Example", "well": "Example", "url": "https://gdr.openei.org/example.pdf",
                      "landing_page": "https://gdr.openei.org/submissions/1", "gdr_submission": 1,
                      "license": {"id": "CC-BY-4.0", "url": "https://creativecommons.org/licenses/by/4.0/"},
                      "sha256": "0" * 64, "bytes": pdf.stat().st_size}
            options = load_options(Path("configs/ingestion/default.json"))
            options["table_mode"] = "accurate"
            options["max_chars"] = 40
            directory = prepare_run(root, "sample", options, [source])
            path = directory / "gdr_chunks.json"
            chunk_documents([source], root, options, output=path)
            self.assertEqual(validate_artifacts(path), [])
            write_json(root / "configs/sources/gdr_end_of_well.json", [source])
            write_json(directory / "metrics.json", {"validated": True, "sha256": sha256(path)})
            publish_run(root, "sample", root / "configs/sources/gdr_end_of_well.json")
            self.assertEqual((root / "data/processed/gdr_chunks.json").read_bytes(), path.read_bytes())
            # An earlier registry with identical IDs must not choose the destination.
            write_json(root / "configs/sources/aaa.json", [source])
            secondary = root / "configs/sources/secondary.json"
            write_json(secondary, [source])
            publish_run(root, "sample", secondary)
            self.assertEqual((root / "data/processed/local/secondary/gdr_chunks.json").read_bytes(), path.read_bytes())
            self.assertFalse((root / "data/processed/local/aaa").exists())
            mismatch = root / "configs/sources/mismatch.json"
            write_json(mismatch, [{**source, "title": "Different registry metadata"}])
            with self.assertRaisesRegex(ValueError, "target --sources"):
                publish_run(root, "sample", mismatch)
            self.assertFalse((root / "data/processed/local/mismatch").exists())
            sidecar = path.with_name("gdr_chunks_full.jsonl")
            records = [json.loads(line) for line in sidecar.read_text().splitlines()]
            records[0]["content_id"] = "0" * 16
            records[1]["row_end"] = 100
            records[0]["char_end"] -= 1
            sidecar.write_text("".join(json.dumps(r) + "\n" for r in records))
            errors = validate_artifacts(path)
            self.assertTrue(any("content_id" in e for e in errors))
            self.assertTrue(any("row range" in e for e in errors))
            self.assertTrue(any("canonical" in e for e in errors))
            with self.assertRaises(ValueError):
                publish_run(root, "sample", root / "configs/sources/gdr_end_of_well.json")
