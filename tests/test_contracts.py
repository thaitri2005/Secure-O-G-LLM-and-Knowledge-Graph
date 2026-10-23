"""Source, command-line and documentation contracts."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from graph_builder.ingestion.__main__ import main
from graph_builder.ingestion.sources import DOC_ID, load_registry, write_json


class ContractTests(unittest.TestCase):
    def test_registry_and_schemas_share_document_id_rule(self):
        source = json.loads(Path("configs/sources/gdr_end_of_well.json").read_text(encoding="utf-8"))[0]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sources.json"
            for identifier in ("Uppercase", "a.b", "_leading", "a" * 65):
                with self.subTest(identifier=identifier):
                    write_json(path, [{**source, "doc_id": identifier}])
                    with self.assertRaisesRegex(ValueError, "doc_id"):
                        load_registry(path)
            write_json(path, [{**source, "doc_id": "a" * 64}])
            self.assertEqual(load_registry(path)[0]["doc_id"], "a" * 64)
        for path in Path("schemas").glob("*.json"):
            properties = json.loads(path.read_text(encoding="utf-8"))["properties"]
            for key in ("doc_id", "parent_doc_id"):
                if key in properties:
                    self.assertEqual(properties[key]["pattern"], DOC_ID.pattern)
                    self.assertEqual(properties[key]["maxLength"], 64)

    def test_cache_documentation_describes_parser_settings(self):
        for path in (Path("README.md"), Path("docs/ingestion.md")):
            self.assertIn("a per-parser-settings subdirectory of `data/interim/docling/`", path.read_text(encoding="utf-8"))

    def test_package_describes_passages_with_provenance(self):
        from graph_builder import ingestion
        from graph_builder.ingestion import chunking
        for description in (ingestion.__doc__, chunking.__doc__, Path("pyproject.toml").read_text(encoding="utf-8")):
            self.assertIn("passage chunks with", description)
            self.assertIn("provenance", description)

    def test_ignored_overrides_fail_before_loading_or_writing(self):
        for command in ("compare", "evaluate", "publish", "ocr"):
            with self.subTest(command=command), patch("sys.argv", ["ingestion", command, "--set", "max_chars=1000", "--run-name", "sample"]), patch("graph_builder.ingestion.__main__.load_registry") as load, contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(), 1)
                load.assert_not_called()
                self.assertIn("does not accept --set", output.getvalue())

    def test_publish_forwards_explicit_target_registry(self):
        target = Path("configs/sources/gdr_end_of_well_extended.json")
        with patch("sys.argv", ["ingestion", "publish", "--run", "sample", "--sources", str(target)]), patch("graph_builder.ingestion.__main__.publish_run") as publish:
            self.assertEqual(main(), 0)
            self.assertEqual(publish.call_args.args[1:], ("sample", target))
