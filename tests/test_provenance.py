"""Test source-coordinate conversion and exact canonical offsets."""
import unittest
import json
from pathlib import Path
import tempfile
from PIL import Image
from docling_core.types.doc import CoordOrigin
from graph_builder.ingestion.provenance import canonical_records, item_regions, merge_regions, page_records, rectangle_area, rounded_geometry
from test_chunking import make_document, add_text
from graph_builder.ingestion.chunking import chunks_from_document


class ProvenanceTests(unittest.TestCase):
    def test_geometry_jitter_serializes_identically_without_changing_text(self):
        from graph_builder.ingestion.sources import write_json
        def record(delta):
            return {"regions": [{"page": 1, "bbox": [10.121 + delta, 20.341 + delta, 30.561 + delta, 40.781 + delta]}],
                    "cells": [{"bbox": {"l": 10.121 + delta}, "text": "Depth 10.1211"}],
                    "pages": {"1": {"width": 600.001 + delta, "height": 800.001 + delta}},
                    "charspan": [1.001 + delta, 4.001 + delta], "char_start": 1,
                    "text": "10.1211\n20.3411"}
        with tempfile.TemporaryDirectory() as temporary:
            paths = [Path(temporary) / name for name in ("first.json", "second.json")]
            for path, delta in zip(paths, (0, .0001)):
                original = record(delta)
                write_json(path, rounded_geometry(original))
                self.assertEqual(original, record(delta))
            self.assertEqual(paths[0].read_bytes(), paths[1].read_bytes())
            saved = json.loads(paths[0].read_text(encoding="utf-8"))
            self.assertEqual(saved["regions"][0]["bbox"], [10.12, 20.34, 30.56, 40.78])
            self.assertEqual(saved["text"], record(0)["text"])
            self.assertEqual(saved["cells"][0]["text"], "Depth 10.1211")
            self.assertIsInstance(saved["char_start"], int)
            self.assertEqual(json.dumps(rounded_geometry(-.0001)), "0.0")

    def test_section_path_retains_heading_hierarchy(self):
        document = make_document(1)
        document.add_heading(text="Outer", level=1)
        document.add_heading(text="Inner", level=2)
        from test_chunking import provenance
        for heading in document.texts:
            heading.prov = [provenance(1, heading.text)]
        add_text(document, "Source passage.")
        metadata = []
        chunks_from_document(document, "sample", 1500, .08, .5, 1, .5, 3, metadata)
        self.assertEqual(metadata[0]["section_path"], ["Outer", "Inner"])

    def test_scan_flag_requires_large_image_and_sparse_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scan.pdf"
            Image.new("RGB", (600, 800), "white").save(path, "PDF")
            self.assertTrue(page_records(path)["1"]["needs_ocr"])
            self.assertTrue(page_records(path, [1])["1"]["needs_ocr"])
            self.assertFalse(page_records(path, [])["1"]["needs_ocr"])

    def test_canonical_offsets_preserve_unicode_and_newlines(self):
        chunks = [{"text": "First\npassage."}, {"text": "Second passage."}]
        canonical, records = canonical_records(chunks, [{}, {}], "parent")
        self.assertEqual(canonical, "First\npassage.\n\nSecond passage.")
        for record in records:
            self.assertEqual(canonical[record["char_start"]:record["char_end"]], record["text"])
            self.assertEqual(record["parent_doc_id"], "parent")
        with self.assertRaises(ValueError):
            canonical_records(chunks, [{}], None)

    def test_coordinate_origin_and_vertical_gap(self):
        doc = make_document()
        first = add_text(doc, "First", top=100, bottom=110, origin=CoordOrigin.BOTTOMLEFT)
        second = add_text(doc, "Second", top=150, bottom=160)
        third = add_text(doc, "Third", top=800, bottom=810)
        regions = item_regions(doc, [(first, 1), (second, 1), (third, 1)])
        self.assertEqual(regions, [{"page": 1, "bbox": [100, 100, 300, 160]}, {"page": 1, "bbox": [100, 800, 300, 810]}])
        self.assertEqual(merge_regions([], {}), [])

    def test_image_union_does_not_double_count_overlap(self):
        self.assertEqual(rectangle_area([[0, 0, 10, 10], [5, 0, 15, 10]]), 150)
        self.assertEqual(rectangle_area([]), 0)
