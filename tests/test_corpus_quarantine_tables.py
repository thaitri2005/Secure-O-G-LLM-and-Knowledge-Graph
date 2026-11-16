"""Producer-side table scan (``chunking.quarantine.scan_tables``): cell reading path, grid geometry, chunk join, OFF identity.
Synthetic word boxes and documents; the PDF is replaced by a fake reader."""
from __future__ import annotations
import unittest
from types import SimpleNamespace
from unittest import mock
from graph_builder.corpus import quarantine as q
from graph_builder.corpus.quarantine import (MARKING_DEFAULT, TABLE_KEYS, chunk_reasons, chunk_sidecar, empty_report, mark_quarantine,
                                             quarantine_settings, scan_tables, table_geometry)
S = quarantine_settings({"scan_tables": True, "mark_review": True})
def w(text, left, top, width=None, height=10.0):
    width = width or 6.0 * len(text)
    return (q._tokens(text), [left, top, left + width, top + height])
def cell(r, c, text, **extra):
    return dict({"r": r, "c": c, "row_span": 1, "col_span": 1, "text": text}, **extra)
def grid_words(rows, left=(10.0, 110.0, 210.0), top=100.0, step=14.0):
    out = []
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            if text:
                out.append(w(text, left[c], top + r * step, width=60.0))
    return out
def scattered_words(rows):
    # every cell at its own x: no two cells of a column (or of a row) share any x (or y) range, as in a grid that does not follow the page
    return [w(text, 10.0 + 25.0 * ((r * 7 + c * 3) % 11), 100.0 + 12.0 * ((r * 5 + c * 2) % 7), width=20.0) for r, row in enumerate(rows) for c, text in enumerate(row)]
ROWS = [["Depth", "Size", "Grade"], ["alpha", "bravo", "charlie"], ["delta", "echo", "foxtrot"], ["golf", "hotel", "india"], ["juliet", "kilo", "lima"]]
def cells_of(rows):
    return [cell(r, c, text) for r, row in enumerate(rows) for c, text in enumerate(row)]
class GeometryTests(unittest.TestCase):
    def test_a_grid_that_follows_the_page_has_no_finding(self):
        result = table_geometry(cells_of(ROWS), grid_words(ROWS), S)
        self.assertEqual((result["jumpy_cells"], result["unmatched"]), ([], 0))
        self.assertGreaterEqual(result["testable"], 8)
    def test_cell_that_joins_a_value_in_front_of_its_labels_is_a_cell_spanning_blocks(self):
        # page: line 1 "Well ID: Forge", line 2 "Report No: 1"; the cell reads "Report 1 Forge Well" (value before label)
        words = [w("Well", 10, 100), w("ID:", 50, 100), w("Forge", 80, 100), w("Report", 10, 114), w("No:", 60, 114), w("1", 100, 114)]
        cells = [cell(0, 0, "Report No: 1 Forge Well ID:")]
        result = table_geometry(cells, words, S)
        self.assertEqual(len(result["jumpy_cells"]), 1)
        self.assertGreaterEqual(result["jumpy_cells"][0]["jumps"], 2)
    def test_wrapped_paragraph_in_one_cell_is_not_a_finding(self):
        words = [w("Fly", 10, 100), w("crews", 40, 100), w("to", 90, 100), w("lodge", 10, 112), w("for", 50, 112), w("meals", 80, 112), w("and", 10, 124), w("rest", 40, 124)]
        self.assertEqual(table_geometry([cell(0, 0, "Fly crews to lodge for meals and rest")], words, S)["jumpy_cells"], [])
    def test_two_tokens_far_apart_on_one_line_count_only_when_they_are_neighbours_in_the_cell(self):
        words = [w("Oper:", 10, 100), w("Cont:", 200, 100), w("Serv:", 400, 100), w("Hours:", 600, 100)]
        found = table_geometry([cell(0, 0, "Oper: Cont: Serv: Hours:")], words, S)["jumpy_cells"]
        self.assertEqual(len(found), 1)  # three wide gaps between neighbours
        skipped = table_geometry([cell(0, 0, "Oper: x Cont: x Serv: x Hours:")], words, S)["jumpy_cells"]
        self.assertEqual(skipped, [])  # not neighbours in the cell text: a gap proves nothing
    def test_scrambled_grid_is_inconsistent_and_a_regular_one_is_not(self):
        result = table_geometry(cells_of(ROWS), scattered_words(ROWS), S)
        self.assertGreaterEqual(result["ratio"], S["table_max_geometry_ratio"])
        self.assertEqual(table_geometry(cells_of(ROWS), grid_words(ROWS), S)["unmatched"], 0)
    def test_too_few_testable_cells_never_decide_the_grid(self):
        rows = [["Depth"], ["alpha"], ["bravo"]]  # scattered, but only 3 testable cells: the grid is not judged
        result = table_geometry(cells_of(rows), scattered_words(rows), S)
        self.assertLess(result["testable"], S["table_min_testable"])
        self.assertEqual(result["ratio"], 1.0)  # the ratio alone would say inconsistent; scan_tables needs table_min_testable
        self.assertEqual(ScanTablesTests().run_scan([table_record(rows)], scattered_words(rows))["findings"], [])
    def test_repeated_tokens_are_not_anchors(self):
        words = [w("0", 10, 100), w("0", 110, 100)]
        result = table_geometry([cell(0, 0, "0"), cell(0, 1, "0")], words, S)
        self.assertEqual((result["anchored_cells"], result["testable"]), (0, 0))
    def test_merged_cells_are_not_part_of_the_column_test(self):
        cells = [cell(0, 0, "Depth", col_span=2), cell(0, 2, "Grade")] + cells_of(ROWS[1:])
        result = table_geometry(cells, grid_words(ROWS), S)
        self.assertEqual(result["unmatched"], 0)
class FakeSource:
    def __init__(self, rotation=0, layer=None):
        self.rotation, self.layer = rotation, layer
    def __call__(self, path, number, upright=False):
        return self.layer
class FakePdf:
    rotation = 0
    def __init__(self, source):
        pass
    def __getitem__(self, index):
        return SimpleNamespace(get_rotation=lambda: FakePdf.rotation)
    def close(self):
        pass
def doc_of(width=600.0, height=800.0):
    return SimpleNamespace(pages={1: SimpleNamespace(size=SimpleNamespace(width=width, height=height))})
def layer_of(words, width=600.0, height=800.0):
    return {"page": 1, "width": width, "height": height, "words": [{"text": t, "bbox": b} for (toks, b), t in words], "text": ""}
def table_record(rows, name="doc#t0000", source_ref="#/tables/0", bbox=(0.0, 90.0, 300.0, 200.0)):
    return {"table_id": name, "source_ref": source_ref, "regions": [{"page": 1, "bbox": list(bbox)}], "cells": cells_of(rows)}
class ScanTablesTests(unittest.TestCase):
    def run_scan(self, tables, words, rotation=0, ocr=frozenset(), source="x.pdf", doc=None, settings=S):
        report = empty_report(settings)
        FakePdf.rotation = rotation
        pairs = [((tokens, box), " ".join(tokens)) for tokens, box in words]
        with mock.patch("pypdfium2.PdfDocument", FakePdf), mock.patch.object(q, "source_page", FakeSource(layer=layer_of(pairs))):
            scan_tables(tables, doc or doc_of(), source, set(ocr), settings, report)
        return report
    def test_regular_table_has_no_finding_and_is_counted_as_examined(self):
        report = self.run_scan([table_record(ROWS)], grid_words(ROWS))
        self.assertEqual((report["findings"], report["tables"]["examined"], report["tables"]["flagged"]), ([], 1, 0))
    def test_scrambled_table_is_reported_with_table_id_source_ref_and_region(self):
        report = self.run_scan([table_record(ROWS)], scattered_words(ROWS))
        self.assertEqual([f["reason"] for f in report["findings"]], ["table_geometry_inconsistent"])
        finding = report["findings"][0]
        self.assertEqual((finding["table_id"], finding["source_ref"], finding["page"]), ("doc#t0000", "#/tables/0", 1))
        self.assertEqual(finding["region"], [0.0, 90.0, 300.0, 200.0])
    def test_unexaminable_tables_are_counted_with_a_reason_never_skipped_silently(self):
        record = table_record(ROWS)
        self.assertEqual(self.run_scan([record], grid_words(ROWS), rotation=90)["tables"]["not_examined"], {"rotated_page": 1})
        self.assertEqual(self.run_scan([record], grid_words(ROWS), ocr={1})["tables"]["not_examined"], {"ocr_page": 1})
        self.assertEqual(self.run_scan([record], grid_words(ROWS), doc=doc_of(700.0, 800.0))["tables"]["not_examined"], {"page_size_mismatch": 1})
        self.assertEqual(self.run_scan([dict(record, regions=[])], grid_words(ROWS))["tables"]["not_examined"], {"no_region": 1})
        self.assertEqual(self.run_scan([record], [])["tables"]["not_examined"], {"little_text_layer_in_region": 1})
        self.assertEqual(self.run_scan([record], grid_words(ROWS), source=None)["tables"]["skipped"], "no_source")
    def test_table_whose_text_is_mostly_not_in_the_text_layer_is_not_judged(self):
        words = grid_words([["Depth", "Size", "Grade"]])
        report = self.run_scan([table_record(ROWS)], words)
        self.assertEqual((report["findings"], report["tables"]["not_examined"]), ([], {"little_text_layer_in_region": 1}))
    def test_rotation_270_page_in_displayed_frame_is_mapped_to_the_upright_frame(self):
        # displayed page 800 x 600; upright layer 600 x 800. Upright box [l,t,r,b] <-> displayed [t, W-r, b, W-l] with W=600
        words = grid_words(ROWS)
        record = table_record(ROWS, bbox=(90.0, 600.0 - 300.0, 200.0, 600.0 - 0.0))
        report = self.run_scan([record], words, rotation=270, doc=doc_of(800.0, 600.0))
        self.assertEqual((report["tables"]["examined"], report["findings"]), (1, []))
    def test_findings_are_capped_but_counted(self):
        settings = quarantine_settings({"scan_tables": True, "max_findings": 1})
        report = self.run_scan([table_record(ROWS, "a#t0"), table_record(ROWS, "a#t1")], scattered_words(ROWS), settings=settings)
        self.assertEqual((len(report["findings"]), report["findings_total"]), (1, 2))
class JoinTests(unittest.TestCase):
    CHUNKS = [{"chunk_id": "f:s1:c0", "type": "text", "text": "Depth Size alpha", "pages": [1], "quality": "ok", "table_id": None},
              {"chunk_id": "f:s1:c1", "type": "table", "text": "| Depth |", "pages": [1], "quality": "ok", "table_id": "doc#t0000"},
              {"chunk_id": "f:s1:c2", "type": "table", "text": "| other |", "pages": [1], "quality": "ok", "table_id": "doc#t0001"}]
    def report(self):
        r = empty_report(S)
        r["findings"] = [{"page": 1, "reason": "table_cell_spans_blocks", "item": "#/tables/0", "table_id": "doc#t0000", "source_ref": "#/tables/0",
                          "text": "Depth", "details": {}}]
        r["findings_total"] = 1
        return r
    def test_table_finding_maps_to_the_chunks_of_that_table_and_not_to_text_chunks_of_the_page(self):
        mapping, stats = chunk_reasons([dict(c) for c in self.CHUNKS], self.report(), None)
        self.assertEqual(mapping, {1: ["table_cell_spans_blocks"]})
        self.assertEqual(stats["mapped_by_table"], 1)
    def test_mark_review_marks_the_table_chunk_only_by_default_reasons(self):
        chunks = [dict(c) for c in self.CHUNKS]
        mark_quarantine(chunks, {"quarantine": self.report()}, S)
        self.assertEqual([c["quality"] for c in chunks], ["ok", "review", "ok"])
        self.assertIn("table_cell_spans_blocks", MARKING_DEFAULT)
        off = [dict(c) for c in self.CHUNKS]
        mark_quarantine(off, {"quarantine": self.report()}, quarantine_settings({"scan_tables": True}))
        self.assertEqual([c["quality"] for c in off], ["ok", "ok", "ok"])
    def test_sidecar_joins_through_the_k1_table_id_and_drops_a_replaced_table(self):
        chunks = [dict(c, table_id={"doc#t0000": "f:t1", "doc#t0001": "f:t2", None: None}[c["table_id"]]) for c in self.CHUNKS]
        statistics = {"quarantine": self.report()}
        side = chunk_sidecar(statistics, chunks, {"doc#t0000": ("f:t1", "#/tables/0"), "doc#t0001": ("f:t2", "#/tables/1")})
        self.assertEqual(side["chunks"], {"f:s1:c1": [{"reason": "table_cell_spans_blocks", "class": "table_association", "source": "quarantine"}]})
        self.assertEqual(side["summary"]["quarantine_tables"], {"findings": 1, "joined": 1, "not_joined": 0, "table_replaced_or_unknown": 0})
        replaced = chunk_sidecar(statistics, chunks, {"doc#t0000": ("f:t1", "textlayer:operations_summary:p1:0")})
        self.assertEqual(replaced["chunks"], {})
        self.assertEqual(replaced["summary"]["quarantine_tables"]["table_replaced_or_unknown"], 1)
    def test_report_without_table_findings_has_no_table_summary(self):
        r = empty_report(quarantine_settings({"scan_visibility": True}))
        side = chunk_sidecar({"quarantine": r}, [dict(c) for c in self.CHUNKS])
        self.assertNotIn("quarantine_tables", side["summary"])
class ConfigTests(unittest.TestCase):
    def test_default_is_off_and_report_of_an_off_run_does_not_echo_the_table_keys(self):
        self.assertFalse(quarantine_settings({})["scan_tables"])
        echoed = empty_report(quarantine_settings({"scan_visibility": True}))["settings"]
        self.assertFalse(set(TABLE_KEYS) & set(echoed))
        self.assertTrue(set(TABLE_KEYS) <= set(empty_report(S)["settings"]))
    def test_invalid_values_are_rejected(self):
        for bad in ({"scan_tables": 1}, {"table_max_geometry_ratio": 1.5}, {"table_min_found_share": -0.1}, {"table_cell_min_jumps": 0},
                    {"table_min_testable": 2.5}, {"table_gap_factor": 99}, {"table_region_grow_pt": "6"}, {"unknown_key": True}):
            with self.assertRaises(ValueError, msg=bad):
                quarantine_settings(bad)
if __name__ == "__main__":
    unittest.main()
