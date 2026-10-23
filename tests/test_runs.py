"""Experiment isolation and explicit publication checks."""
import json
from pathlib import Path
import tempfile
import unittest

from graph_builder.ingestion.runs import bundle_directory, compare_runs, conversion_cache, prepare_run, publish_run, run_directory
from graph_builder.ingestion.sources import load_options, write_json
from graph_builder.ingestion.chunking import chunk_documents
from test_chunking import make_document, add_text


class RunTests(unittest.TestCase):
    def test_registry_layout_preserves_main_and_isolates_secondary(self):
        root = Path("repository")
        self.assertEqual(bundle_directory(root, "gdr_end_of_well"), root / "data/processed")
        for name in ("gdr_end_of_well_extended", "gdr_ak3_appendices", "another_registry"):
            self.assertEqual(bundle_directory(root, name), root / "data/processed/local" / name)
        for name in ("../escape", "a/b", ""):
            with self.assertRaises(ValueError):
                bundle_directory(root, name)

    def test_cache_tracks_parser_options_only(self):
        options = load_options(Path("configs/ingestion/default.json"))
        original = conversion_cache(Path("."), options)
        options["max_chars"] = 1000
        self.assertEqual(original, conversion_cache(Path("."), options))
        options["table_mode"] = "accurate" if options["table_mode"] == "fast" else "fast"
        self.assertNotEqual(original, conversion_cache(Path("."), options))

    def test_names_reject_traversal(self):
        for name in ("../escape", "a/b", "", "C:drive", "UPPER"):
            with self.assertRaises(ValueError):
                run_directory(Path("."), name)
        self.assertEqual(run_directory(Path("."), "paragraph_1500_accurate").name, "paragraph_1500_accurate")

    def test_chunk_output_cannot_replace_published_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = make_document()
            from pypdf import PdfWriter
            pdf = root / "data/raw/sample.pdf"
            pdf.parent.mkdir(parents=True)
            writer = PdfWriter()
            for _ in range(2):
                writer.add_blank_page(width=600, height=1000)
            writer.write(pdf)
            add_text(document, "A source passage.")
            write_json(root / "data/interim/docling/sample.json", document.export_to_dict())
            destination = root / "data/processed/gdr_chunks.json"
            write_json(destination, [])
            original = destination.read_bytes()
            options = load_options(Path("configs/ingestion/default.json"))
            with self.assertRaisesRegex(ValueError, "publish"):
                chunk_documents([{"doc_id": "sample"}], root, options)
            self.assertEqual(original, destination.read_bytes())
            output = run_directory(root, "sample") / "gdr_chunks.json"
            result, _ = chunk_documents([{"doc_id": "sample"}], root, options, output=output)
            self.assertEqual(len(result), 1)
            self.assertEqual(original, destination.read_bytes())

    def test_changed_protected_run_preserves_every_published_file(self):
        from pypdf import PdfWriter
        from graph_builder.ingestion.sources import write_checksums
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf = root / "data/raw/sample.pdf"
            pdf.parent.mkdir(parents=True)
            writer = PdfWriter()
            writer.add_blank_page(width=600, height=1000)
            writer.write(pdf)
            document = make_document(1)
            add_text(document, "A source passage.")
            cache = root / "data/interim/docling/sample.json"
            write_json(cache, document.export_to_dict())
            options = load_options(Path("configs/ingestion/default.json"))
            registry = [{"doc_id": "sample"}]
            destination = root / "data/processed"
            chunk_documents(registry, root, options)
            write_json(destination / "local/other/untouched.json", {"keep": True})
            snapshot = {path.relative_to(destination): path.read_bytes() for path in destination.rglob("*") if path.is_file()}
            for change in ("text", "geometry", "document_metadata", "table_sidecar"):
                with self.subTest(change=change):
                    changed = document.model_copy(deep=True)
                    settings = dict(options)
                    if change == "text":
                        changed.texts[0].text = "Changed source passage."
                    elif change == "geometry":
                        changed.texts[0].prov[0].bbox.l += 1
                    elif change == "document_metadata":
                        settings["max_chars"] += 1
                    else:
                        (destination / "gdr_tables.jsonl").write_bytes(b"altered shared tables\n")
                        write_checksums(destination, ["sample"])
                    before = {path.relative_to(destination): path.read_bytes() for path in destination.rglob("*") if path.is_file()}
                    write_json(cache, changed.export_to_dict())
                    with self.assertRaisesRegex(ValueError, "publish"):
                        chunk_documents(registry, root, settings)
                    after = {path.relative_to(destination): path.read_bytes() for path in destination.rglob("*") if path.is_file()}
                    self.assertEqual(before, after)
                    for relative, value in snapshot.items():
                        (destination / relative).write_bytes(value)

    def test_resolved_options(self):
        config = Path("configs/ingestion/default.json")
        self.assertEqual(load_options(config, ["max_chars=1000", "chunking.strategy=paragraph"])["max_chars"], 1000)
        for value in ("max_chars=0", "unknown=1", "chunking.strategy=wrong", "no_separator"):
            with self.assertRaises(ValueError):
                load_options(config, [value])

    def test_prepare_compare_publish(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = prepare_run(root, "old", {}, [])
            new = prepare_run(root, "new", {}, [])
            with self.assertRaises(ValueError):
                prepare_run(root, "old", {"different": True}, [])
            record = {"doc_id": "sample", "type": "text", "text": "A passage."}
            write_json(old / "gdr_chunks.json", [record, record])
            write_json(new / "gdr_chunks.json", [record])
            self.assertEqual(compare_runs(root, "old", "new"), {"kept": 1, "changed": 0, "added": 0, "removed": 1})
            source = json.loads(Path("configs/sources/gdr_end_of_well.json").read_text(encoding="utf-8"))[0]
            write_json(root / "configs/sources/gdr_end_of_well.json", [source])
            with self.assertRaises(ValueError):
                publish_run(root, "new", root / "configs/sources/gdr_end_of_well.json")
            (new / "documents").mkdir()
            (new / "gdr_chunks_full.jsonl").write_text(json.dumps(record) + "\n")
            write_json(new / "metrics.json", {"validated": False})
            with self.assertRaises(ValueError):
                publish_run(root, "new", root / "configs/sources/gdr_end_of_well.json")
            write_json(new / "metrics.json", {"validated": True})
            with self.assertRaises(ValueError):
                publish_run(root, "new", root / "configs/sources/gdr_end_of_well.json")

    def test_compare_content_identity_and_one_to_one_similarity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = prepare_run(root, "old", {}, [])
            new = prepare_run(root, "new", {}, [])
            base = {"doc_id": "sample", "type": "text", "text": "one two three four five six seven eight nine ten"}
            write_json(old / "gdr_chunks.json", [base, base, {**base, "text": "Whitespace  only"}])
            write_json(new / "gdr_chunks.json", [{**base, "text": base["text"] + " eleven"}, {**base, "text": "Whitespace only"}])
            self.assertEqual(compare_runs(root, "old", "new"), {"kept": 1, "changed": 1, "added": 0, "removed": 1})
