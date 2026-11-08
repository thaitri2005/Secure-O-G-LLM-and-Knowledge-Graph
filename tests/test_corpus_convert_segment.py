"""A cold conversion and a later cached read of the same segment must give identical documents and metadata."""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest import mock

from docling.datamodel.base_models import ConversionStatus
from docling_core.types.doc import BoundingBox, CoordOrigin, DocItemLabel, ProvenanceItem

from graph_builder.corpus import process
from graph_builder.corpus.chunking import chunk_document
from test_chunking import add_text, make_document

CONFIG = {"chunking": {"max_chars": 1500, "strategy": "paragraph"},
          "filters": {"margin_band": 0.08, "frequency": 0.5, "running_block_max_gap_lines": 1.0,
                      "running_block_alignment_lines": 0.5, "running_line_fragment_gap_lines": 3.0}}


def overhanging_document():
    """One page whose text box extends below the page edge, which Docling clamps when it reads JSON back."""
    document = make_document(pages=1)
    add_text(document, "Opening paragraph of the report.", top=300, bottom=310)
    box = BoundingBox(l=100, t=500, r=300, b=-20, coord_origin=CoordOrigin.BOTTOMLEFT)
    document.add_text(label=DocItemLabel.TEXT, text="Paragraph overhanging the page bottom.",
                      prov=ProvenanceItem(page_no=1, bbox=box, charspan=(0, 37)))
    return document


class ConvertSegmentTests(unittest.TestCase):
    def convert_twice(self, directory: Path):
        live = overhanging_document()
        result = SimpleNamespace(status=ConversionStatus.SUCCESS, document=live,
                                 confidence=SimpleNamespace(pages={}), errors=[])
        convert = mock.Mock(return_value=result)
        source, cache = directory / "input.pdf", directory / "segments" / "00001-00001-text.json.gz"
        with mock.patch.object(process, "converter", return_value=mock.Mock(convert=convert)):
            cold = process.convert_segment(source, "pdf", "text", (1, 1), cache, {}, directory)
            cached = process.convert_segment(source, "pdf", "text", (1, 1), cache, {}, directory)
        return live, cold, cached, convert

    def test_cold_and_cached_documents_serialize_identically(self) -> None:
        with TemporaryDirectory() as folder:
            live, (cold, _), (cached, _), convert = self.convert_twice(Path(folder))
        self.assertEqual(convert.call_count, 1)
        self.assertIsNot(cold, live)
        self.assertEqual(cold.model_dump_json(), cached.model_dump_json())

    def test_cold_and_cached_chunks_and_regions_are_identical(self) -> None:
        with TemporaryDirectory() as folder:
            _, (cold, _), (cached, _), _ = self.convert_twice(Path(folder))
        first = chunk_document(cold, "sample", CONFIG, set())
        second = chunk_document(cached, "sample", CONFIG, set())
        self.assertTrue(first[0])
        self.assertEqual(first, second)

    def test_cold_and_cached_metadata_are_identical(self) -> None:
        with TemporaryDirectory() as folder:
            _, (_, cold_meta), (_, cached_meta), _ = self.convert_twice(Path(folder))
        self.assertEqual(cold_meta, cached_meta)
        self.assertEqual(cold_meta["pages"], [1, 1])
        self.assertEqual(cold_meta["status"], "success")


if __name__ == "__main__":
    unittest.main()
