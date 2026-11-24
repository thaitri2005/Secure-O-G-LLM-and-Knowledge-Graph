from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from docling_core.types.doc import BoundingBox, CoordOrigin, DoclingDocument, Size, TableCell, TableData
from docling_core.types.doc.document import ProvenanceItem
import pymupdf

from graph_builder.corpus import numeric_cells
from graph_builder.corpus.qa.cell_evidence import CellEvidence
from graph_builder.corpus.qa.numeric_review import project
from graph_builder.corpus.store import atomic_write_jsonl
from graph_builder.ingestion.tables import table_views


def box(rect):
    l, t, r, b = rect
    return BoundingBox(l=l, t=t, r=r, b=b, coord_origin=CoordOrigin.TOPLEFT)


class NativeNumericCellTests(unittest.TestCase):
    def fixture(self, directory, second_text="37", tight=False, crosses=False, extra_printed=False):
        path = Path(directory) / "different-layout.pdf"
        original = [["Fluid", "Pressure"], ["Base mud", "-53.5"], ["Other fluid", second_text]]
        with pymupdf.open() as pdf:
            page = pdf.new_page(width=300, height=300)
            for y in (35, 58, 81, 104):
                page.draw_line((20, y), (244, y))
            for x in (20, 143, 244):
                page.draw_line((x, 35), (x, 104))
            for y, row in zip((50, 73, 96), original, strict=True):
                for x, value in zip((30, 175), row, strict=True):
                    page.insert_text((x, y), value)
            if extra_printed:
                page.insert_text((25, 235), "Unrelated reference 82")
            pdf.save(path)
        doc = DoclingDocument(name="pressure-table")
        doc.add_page(page_no=1, size=Size(width=300, height=300))
        native = []
        with pymupdf.open(path) as pdf:
            for r, row in enumerate(original):
                for c, value in enumerate(row):
                    printed = value.split()[-1] if tight and (r, c) == (2, 1) else value
                    area = pymupdf.Rect(20 + 123 * c, 35 + 23 * r, 143 + 101 * c, 58 + 23 * r)
                    (rect,) = pdf[0].search_for(printed, clip=area)
                    if crosses and (r, c) == (2, 1):
                        rect.y1 = 109  # Locatable printed word, native rectangle extends outside the rules.
                    text = "82 37" if (r, c) == (2, 1) else value
                    native.append(TableCell(text=text, bbox=box(rect), column_header=r == 0,
                                            start_row_offset_idx=r, end_row_offset_idx=r + 1,
                                            start_col_offset_idx=c, end_col_offset_idx=c + 1))
        item = doc.add_table(data=TableData(num_rows=3, num_cols=2, table_cells=native),
                             prov=ProvenanceItem(page_no=1, bbox=box((20, 35, 244, 104)), charspan=(0, 0)))
        grid, rows, cells, header_rows = table_views(item)
        label = item.self_ref
        part = dict(page=1, source_ref=label, row_start=0, row_end=3)
        table = dict(table_id="final-id", file_id="test-file", doc_id="other-operator", logical_id="raw-id",
                     parts=[part], num_rows=3, num_cols=2, grid=grid, rows_text=rows, cells=cells,
                     header_rows=header_rows, pages=[1])
        text = "Drawdown checks\n| Fluid | Pressure |\n| --- | --- |\n| Base mud | -53.5 |\n| Other fluid | 82 37 |"
        spans = [dict(source_ref=label, page=1, start=0, end=len(text), source_start=0, source_end=41)]
        chunk = dict(table_id="raw-id", type="table", pages=[1], ocr=False, row_start=1, row_end=3,
                     text=text, source_spans=spans)
        return path, item, table, chunk

    def repair(self, path, item, table, chunks):
        return numeric_cells.repair_document(path, [{"page": 1, "mode": "text", "rotation": 0}], [table], chunks,
                                             lambda: {item.self_ref: item})

    def test_real_pdf_geometry_repairs_grid_markdown_and_evidence(self):
        with TemporaryDirectory() as directory:
            path, item, table, chunk = self.fixture(directory)
            self.assertEqual(self.repair(path, item, table, [chunk]), [])
            self.assertEqual(table["grid"][2], ["Other fluid", "37"])
            self.assertIn("Pressure: 37", table["rows_text"][-1])
            self.assertTrue(chunk["text"].endswith("| Other fluid | 37 |"))
            self.assertIn("-53.5", chunk["text"])
            self.assertEqual(chunk["source_spans"][0]["end"], len(chunk["text"]))
            self.assertEqual(item.data.grid[2][1].text, "82 37")
            change, = table["parts"][0]["numeric_repairs"]
            self.assertEqual((change["previous"], change["value"]), ("82 37", "37"))
            with pymupdf.open(path) as pdf:
                words = pdf[0].get_text("words")
                rows = list(CellEvidence.native_rows(table, item, 300, words, [], 300))
                self.assertEqual(rows[-1]["status"], "source_supported")
                self.assertEqual(rows[-1]["observed_text"], "37")
                self.assertEqual(rows[-2]["status"], "text_matches_region")

    def test_two_values_in_one_source_cell_survive_even_if_native_box_is_tight(self):
        with TemporaryDirectory() as directory:
            path, item, table, chunk = self.fixture(directory, "82 37", tight=True)
            original = deepcopy((table, chunk))
            findings = self.repair(path, item, table, [chunk])
            self.assertEqual(findings[0]["reason"], "numeric_cell_geometry_ambiguous")
            self.assertEqual(chunk.pop("quality"), "review")
            self.assertEqual((table, chunk), original)

    def test_reader_disagreement_abstains_before_editing_the_grid(self):
        with TemporaryDirectory() as directory:
            path, item, table, chunk = self.fixture(directory)
            with patch.object(numeric_cells, "source_page", return_value={"words": []}):
                findings = self.repair(path, item, table, [chunk])
            self.assertEqual(findings[0]["reason"], "numeric_cell_readers_disagree")
            self.assertEqual(table["grid"][2][1], "82 37")
            self.assertEqual(chunk["quality"], "review")

    def test_unmapped_and_duplicate_markdown_rows_keep_original_values(self):
        with TemporaryDirectory() as directory:
            path, item, table, chunk = self.fixture(directory)
            for chunks in ([dict(chunk, text=chunk["text"].replace("82 37", "39"))], [chunk, deepcopy(chunk)]):
                with self.subTest(copies=len(chunks)):
                    raw = deepcopy((table, chunks))
                    findings = self.repair(path, item, table, chunks)
                    self.assertEqual(findings[0]["reason"], "numeric_cell_chunk_mapping_unproven")
                    self.assertTrue(all(candidate.pop("quality") == "review" for candidate in chunks))
                    self.assertEqual((table, chunks), raw)

    def test_border_crossing_repair_requires_complete_word_and_coverage(self):
        with TemporaryDirectory() as directory:
            path, item, table, chunk = self.fixture(directory, crosses=True)
            self.assertEqual(self.repair(path, item, table, [chunk]), [])
            repair, = table["parts"][0]["numeric_repairs"]
            self.assertEqual(repair["value"], "37")
            self.assertIn("focus", repair)
            with pymupdf.open(path) as pdf:
                evidence = list(CellEvidence.native_rows(table, item, 300, pdf[0].get_text("words"), [], 300))
            self.assertEqual(evidence[-1]["status"], "source_supported")

        with TemporaryDirectory() as directory:
            path, item, table, chunk = self.fixture(directory, crosses=True, extra_printed=True)
            issue, = self.repair(path, item, table, [chunk])
            self.assertEqual(issue["reason"], "numeric_cell_source_coverage_unproven")
            self.assertEqual(table["grid"][2][1], "82 37")

    def test_retrieval_marks_unresolved_value_only_if_it_is_still_present(self):
        with TemporaryDirectory() as directory:
            _, _, table, chunk = self.fixture(directory)
            root = Path(directory)
            chunk = dict(chunk, table_id="final-id", chunk_id="final-id:c0")
            finding = {"table_id": "final-id", "rule": numeric_cells.RULE, "r": 2, "c": 1, "reason": "ambiguous"}
            manifest = {"table_findings": {"file": [finding]}}
            atomic_write_jsonl(root / "tables.jsonl", [table])
            edits = []
            marked, = project([chunk], root, manifest, edits)
            self.assertTrue(marked["text"].endswith("| Other fluid | [unverified: 82 37] |"))
            self.assertEqual(marked["numeric_review"], [{"r": 2, "c": 1, "reason": "ambiguous"}])
            masked = dict(chunk, text=chunk["text"].replace("82 37", ""))
            self.assertEqual(list(project([masked], root, manifest, [])), [masked])
