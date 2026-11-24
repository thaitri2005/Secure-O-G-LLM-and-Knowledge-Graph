"""Check geometry-backed suppression in the table retrieval view."""
import gzip
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from docling_core.types.doc import BoundingBox, CoordOrigin, DoclingDocument, Size, TableCell, TableData
from docling_core.types.doc.document import ProvenanceItem

from graph_builder.corpus.ops_tables import grid_table_record, markdown
from graph_builder.corpus.qa.table_overlap import TableOverlap
from graph_builder.corpus.store import atomic_write_json, atomic_write_jsonl, file_sha256, read_jsonl
from graph_builder.ingestion.tables import table_views


FILE = {"file_id": "file", "doc_id": "report", "sha256": "a" * 64}
PAGE = {"file_id": "file", "doc_id": "report", "page": 1, "pages": [1], "context": {"well": "AB-1"}, "ocr": False}
FINGERPRINT = "0123456789abcdef"
RUN = [["From", "To", "Description"], ["0:00", "6:00", "Drilled 10 m"]]


def bound(coords):
    l, t, r, b = coords
    return BoundingBox(l=l, t=t, r=r, b=b, coord_origin=CoordOrigin.TOPLEFT)


def provenance(coords, count):
    return ProvenanceItem(page_no=1, bbox=bound(coords), charspan=(0, count))


def chunk(chunk_id, tbl, text, headers, end, quality="ok"):
    return {**PAGE, "type": "table", "chunk_id": chunk_id, "table_id": tbl, "text": text,
            "row_start": headers, "row_end": end, "child_index": 0, "quality": quality}


class TableOverlapTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.release = self.root / "release"
        self.release.mkdir()
        self.work = self.root / "work" / FILE["doc_id"] / FINGERPRINT
        self.work.mkdir(parents=True)
        atomic_write_json(self.release / "manifest.json", {"corpus_fingerprint": FINGERPRINT})
        atomic_write_jsonl(self.release / "files.jsonl", [FILE])
        self.document = DoclingDocument(name="report")
        self.document.add_page(page_no=1, size=Size(width=600, height=800))

    def save_native(self, rotation=0):
        atomic_write_json(self.work / "document.json", {**FILE, "pages": [{"page": 1, "rotation": rotation, "mode": "text"}]})
        with gzip.open(self.work / "docling.json.gz", "wt", encoding="utf-8") as stream:
            stream.write(self.document.model_dump_json())
        self.seal_native()

    def seal_native(self):
        atomic_write_json(self.work / "manifest.json", {"files": {name: file_sha256(self.work / name)
                          for name in ("document.json", "docling.json.gz")}})

    def source_records(self, source_text=None):
        ref = "textlayer:hourly_operations:p1:1"
        box = [10, 100, 500, 200]
        table = grid_table_record("hourly", "report", ref, 1, box, RUN)
        table.update(file_id="file", parts=[{"source_ref": ref, "page": 1, "bbox": box}])
        return table, chunk("hourly-c0", "hourly", markdown(RUN) if source_text is None else source_text, 1, 2)

    def write_release(self, *additional_chunks, tables=(), source_text=None):
        table, passage = self.source_records(source_text)
        atomic_write_jsonl(self.release / "tables.jsonl", [table, *tables])
        atomic_write_jsonl(self.release / "chunks.jsonl", [passage, *additional_chunks])
        return TableOverlap(self.release, self.root)

    def test_deduplicates_a_matching_span_and_keeps_other_occurrences(self):
        text, spans = "", []
        values = [("6:00", 135), ("6:00", 245), ("Drilled 10 ft", 150), ("Rig check", 230)]
        for value, top in values:
            item = self.document.add_text(label="text", text=value, prov=provenance([50, top, 130, top + 10], len(value)))
            line = value + "\n"
            spans.append({"source_ref": item.self_ref, "page": 1, "start": len(text), "end": len(text) + len(line),
                          "source_start": 0, "source_end": len(value)})
            text += line
        body = {**PAGE, "type": "text", "chunk_id": "text", "source_spans": spans, "text": text}
        self.save_native()
        state = self.write_release(body)
        source_bytes = (self.release / "chunks.jsonl").read_bytes()
        projected = list(state.project(read_jsonl(self.release / "chunks.jsonl")))
        self.assertEqual(projected[1]["text"], "6:00\nDrilled 10 ft\nRig check")
        self.assertEqual(state.findings["file", 1][0]["removed_spans"],
                         [{"source_ref": spans[0]["source_ref"], "start": 0, "end": 5}])
        self.assertEqual((self.release / "chunks.jsonl").read_bytes(), source_bytes)

    def test_preserves_neighbors_when_masking_duplicate_native_cells(self):
        grid = [["Misc", "Time", "Notes"], ["0:00", "6:00", "10 50"], ["0:00", "6:00", "Other shift"]]
        cells = [TableCell(text=value, start_row_offset_idx=r, end_row_offset_idx=r + 1,
                           start_col_offset_idx=c, end_col_offset_idx=c + 1, column_header=r == 0,
                           bbox=bound([30 + c * 40, 90 + r * 65, 67 + c * 40, 100 + r * 65]))
                 for r, line in enumerate(grid) for c, value in enumerate(line)]
        item = self.document.add_table(data=TableData(num_rows=3, num_cols=3, table_cells=cells),
                                       prov=provenance([30, 90, 200, 260], 0))
        _, _, grid_cells, _ = table_views(item)
        record = {"table_id": "native", "file_id": "file", "grid": grid, "cells": grid_cells,
                  "num_rows": 3, "num_cols": 3, "header_rows": 1,
                  "parts": [{"source_ref": item.self_ref, "page": 1}]}
        self.save_native()
        native = chunk("native-c0", "native", markdown(grid), 1, 3, quality="review")
        state = self.write_release(native, tables=[record])
        self.assertEqual(state.replacements["native-c0"].splitlines()[-2:],
                         ["| | | 10 50 |", "| 0:00 | 6:00 | Other shift |"])
        self.assertEqual(state.findings["file", 1][0]["removed_cells"], [[1, 0], [1, 1]])

        patch = {"r": 1, "c": 2, "previous": "10 50", "value": "50", "focus": [115, 158, 125, 165]}
        record["parts"][0]["numeric_repairs"] = [patch]
        record["grid"][1][2] = "50"
        next(cell for cell in grid_cells if (cell["r"], cell["c"]) == (1, 2))["text"] = "50"
        native["text"] = markdown(record["grid"])
        state = self.write_release(native, tables=[record])
        self.assertEqual(state.replacements["native-c0"].splitlines()[-2:],
                         ["| | | 50 |", "| 0:00 | 6:00 | Other shift |"])
        patch["previous"] = "20 50"
        self.assertFalse(self.write_release(native, tables=[record]).replacements)

    def test_abstains_if_rendering_context_or_cache_disagrees(self):
        item = self.document.add_text(label="text", text="6:00", prov=provenance([50, 140, 130, 150], 4))
        span = {"source_ref": item.self_ref, "page": 1, "start": 0, "end": 4, "source_start": 0, "source_end": 4}
        body = {**PAGE, "type": "text", "chunk_id": "text", "source_spans": [span], "text": "6:00"}
        self.save_native()
        self.assertFalse(self.write_release(dict(body, context={"well": "OTHER"})).replacements)
        self.assertFalse(self.write_release(body, source_text=markdown([["X", "Y", "Z"], ["0:00", "6:00", "Drilled 10 m"]])).replacements)
        self.assertEqual(self.write_release(body).replacements, {"text": ""})
        with (self.work / "docling.json.gz").open("ab") as stream:
            stream.write(b"changed")
        self.assertFalse(self.write_release(body).replacements)
        self.save_native(rotation=90)
        self.assertFalse(self.write_release(body).replacements)


if __name__ == "__main__":
    unittest.main()
