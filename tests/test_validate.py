"""Check accepted records and targeted failures for schema, identifiers, coverage, size exceptions, and source integrity."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from docling_core.types.doc import DocItemLabel, TableData

from graph_builder.ingestion.sources import fetch_sources, load_options, load_registry, write_json
from graph_builder.ingestion.validate import Source, exempt_pages, validate_records
from test_chunking import add_text, make_document, provenance

ROOT = Path(__file__).resolve().parents[1]


class ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.options = load_options(ROOT / "configs/ingestion/default.json")
        self.options["spot_checks"] = []
        document = make_document()
        add_text(document, "Body text.")
        self.sources = {"sample": Source(document, [300, 0])}
        self.records = [{"doc_id": "sample", "page": 1, "chunk_id": "sample#c0000", "type": "text", "text": "Body text.", "section": "Overview"},
                        {"doc_id": "sample", "page": 1, "chunk_id": "sample#c0001", "type": "table", "text": "| H |\n| --- |\n| V |", "section": "Overview"}]

    def validate(self, records: object = None) -> tuple[list[str], list[str], list[dict]]:
        return validate_records(self.records if records is None else records, list(self.sources), self.sources, self.options)

    def test_valid_records(self) -> None:
        errors, warnings, summary = self.validate()
        self.assertEqual((errors, warnings), ([], []))
        self.assertEqual(summary[0]["total"], 2)

    def test_full_header_plus_one_body_row_warns(self):
        self.options["max_chars"] = 30
        self.records[1]["text"] = "| Header text |\n| --- |\n| Body row text |"
        errors, warnings, _ = self.validate()
        self.assertFalse(errors)
        self.assertEqual(len(warnings), 1)

    def test_full_header_plus_two_body_rows_fails(self):
        self.options["max_chars"] = 30
        self.records[1]["text"] = "| Header text |\n| --- |\n| First body row |\n| Second body row |"
        self.assertTrue(self.validate()[0])

    def test_headerless_single_body_row_warns(self):
        self.options["max_chars"] = 30
        self.records[1]["text"] = "| A single body row longer than the budget |"
        errors, warnings, _ = self.validate()
        self.assertFalse(errors)
        self.assertEqual(len(warnings), 1)
        self.records[1]["type"] = "text"
        self.assertTrue(self.validate()[0])

    def test_top_level_empty_and_nonobject(self) -> None:
        for value in ({}, [], ["record"]):
            with self.subTest(value=value):
                self.assertTrue(self.validate(value)[0])

    def test_required_and_extra_fields(self) -> None:
        for key in ("doc_id", "page", "chunk_id", "type", "text", "section"):
            records = copy.deepcopy(self.records)
            del records[0][key]
            with self.subTest(missing=key):
                self.assertTrue(self.validate(records)[0])
        records = copy.deepcopy(self.records)
        records[0]["metadata"] = "unexpected"
        self.assertTrue(self.validate(records)[0])

    def test_field_types_and_values(self) -> None:
        cases = [("doc_id", []), ("doc_id", "bad id"), ("doc_id", "unknown"),
                 ("page", True), ("page", 0), ("page", 3), ("page", "1"),
                 ("chunk_id", 12), ("chunk_id", "sample#c001"),
                 ("type", []), ("type", "picture"), ("text", None), ("text", " \n"), ("section", [])]
        for key, value in cases:
            records = copy.deepcopy(self.records)
            records[0][key] = value
            with self.subTest(key=key, value=value):
                self.assertTrue(self.validate(records)[0])
        records = copy.deepcopy(self.records)
        records[0]["section"] = None
        self.assertFalse(self.validate(records)[0])

    def test_duplicate_and_discontinuous_ids(self) -> None:
        for identifier in ("sample#c0000", "sample#c0003"):
            records = copy.deepcopy(self.records)
            records[1]["chunk_id"] = identifier
            self.assertTrue(self.validate(records)[0])

    def test_document_order_and_missing_document(self) -> None:
        self.sources["second"] = self.sources["sample"]
        second = dict(self.records[0], doc_id="second", chunk_id="second#c0000")
        self.assertFalse(self.validate(self.records + [second])[0])
        self.assertTrue(self.validate([second] + self.records)[0])
        self.assertTrue(self.validate()[0])

    def test_coverage_and_exact_character_threshold(self) -> None:
        self.sources["sample"].page_chars[1] = 200
        self.assertFalse(self.validate()[0])
        self.sources["sample"].page_chars[1] = 201
        add_text(self.sources["sample"].document, "Substantive second page", page=2)
        self.assertTrue(self.validate()[0])
        records = copy.deepcopy(self.records)
        records[1]["page"] = 2
        self.assertFalse(self.validate(records)[0])

    def test_dynamic_index_exemption_and_retained_items(self) -> None:
        document = self.sources["sample"].document
        self.sources["sample"].page_chars[1] = 300
        add_text(document, "Figures", page=2, label=DocItemLabel.SECTION_HEADER)
        add_text(document, "Chart .... 9", page=2, label=DocItemLabel.DOCUMENT_INDEX)
        self.assertEqual(exempt_pages(document, self.options), [2])
        self.assertFalse(self.validate()[0])
        heading = add_text(document, "Unrelated heading", page=2, label=DocItemLabel.SECTION_HEADER)
        self.assertEqual(exempt_pages(document, self.options), [])
        self.assertTrue(self.validate()[0])
        heading.label = DocItemLabel.PAGE_HEADER
        caption = add_text(document, "Retained caption", page=2, label=DocItemLabel.CAPTION)
        self.assertEqual(exempt_pages(document, self.options), [])
        caption.label = DocItemLabel.PAGE_FOOTER
        document.add_table(data=TableData(), prov=provenance(2))
        self.assertEqual(exempt_pages(document, self.options), [])

    def test_index_running_metadata_and_header_template(self) -> None:
        document = self.sources["sample"].document
        add_text(document, "Example Report", page=1, top=40, bottom=100, label=DocItemLabel.PAGE_HEADER)
        add_text(document, "Example Report", page=2, top=40, bottom=100, label=DocItemLabel.SECTION_HEADER)
        add_text(document, "Tables", page=2, label=DocItemLabel.SECTION_HEADER)
        add_text(document, "Data .... 8", page=2, label=DocItemLabel.DOCUMENT_INDEX)
        for page in (1, 2):
            add_text(document, "Reference 42", page, 50, 60, left=400, right=500)
            add_text(document, f"Version Page {page}", page, 68, 78, left=400, right=500)
            add_text(document, "Published May", page, 86, 96, left=400, right=500)
        self.assertEqual(exempt_pages(document, self.options), [2])
        # A repeated metadata-only page without an index is not exempt.
        other = make_document()
        for page in (1, 2):
            add_text(other, "Reference 42", page, 50, 60)
        self.assertEqual(exempt_pages(other, self.options), [])

    def test_no_table_warns_without_failing(self) -> None:
        errors, warnings, _ = self.validate(self.records[:1])
        self.assertFalse(errors)
        self.assertEqual(len(warnings), 1)

    def test_text_limit_and_single_row_exception(self) -> None:
        records = copy.deepcopy(self.records)
        records[0]["text"] = "x" * self.options["max_chars"]
        self.assertFalse(self.validate(records)[0])
        records[0]["text"] += "x"
        self.assertTrue(self.validate(records)[0])
        records[0]["text"] = "Body text."
        records[1]["text"] = "| H |\n| --- |\n| " + "x" * 1600 + " |"
        errors, warnings, _ = self.validate(records)
        self.assertFalse(errors)
        self.assertEqual(len(warnings), 1)
        records[1]["text"] += "\n| Second row |"
        self.assertTrue(self.validate(records)[0])
        records[1]["text"] = "| H |\n| " + "-" * 1600 + " |\n| short |"
        self.assertTrue(self.validate(records)[0])

    def test_configured_content_check(self) -> None:
        self.options["spot_checks"] = [{"doc_id": "sample", "page": 1, "section": "Overview", "contains": ["Body", "text."]}]
        self.assertFalse(self.validate()[0])
        self.options["spot_checks"][0]["contains"] = ["Missing phrase"]
        self.assertTrue(self.validate()[0])


class SourceValidationTests(unittest.TestCase):
    def test_registry_and_options_reject_invalid_entries(self) -> None:
        registry = load_registry(ROOT / "configs/sources/gdr_end_of_well.json")
        options = load_options(ROOT / "configs/ingestion/default.json")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.json"
            for key, value in (("bytes", 0), ("sha256", "wrong"), ("url", "https://example.org/report.pdf"), ("doc_id", "bad id")):
                invalid = copy.deepcopy(registry)
                invalid[0][key] = value
                write_json(path, invalid)
                with self.subTest(key=key), self.assertRaises(ValueError):
                    load_registry(path)
            for key, value in (("max_chars", 0), ("frequency", 0), ("margin_band", .9), ("do_ocr", "true"), ("device", "cuda")):
                invalid = dict(options, **{key: value})
                write_json(path, invalid)
                with self.subTest(key=key), self.assertRaises(ValueError):
                    load_options(path)

    def test_fetch_verifies_cached_size_and_hash_without_network(self) -> None:
        payload = b"small synthetic file"
        source = {"doc_id": "sample", "url": "https://gdr.openei.org/example.pdf", "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        with tempfile.TemporaryDirectory() as temporary, patch("graph_builder.ingestion.sources.open_gdr") as network:
            root = Path(temporary)
            path = root / "data/raw/sample.pdf"
            path.parent.mkdir(parents=True)
            path.write_bytes(payload)
            self.assertTrue(fetch_sources([source], root)[0]["cached"])
            path.write_bytes(b"X" * len(payload))
            with self.assertRaises(ValueError):
                fetch_sources([source], root)
            path.write_bytes(payload + b"X")
            with self.assertRaises(ValueError):
                fetch_sources([source], root)
            network.assert_not_called()
