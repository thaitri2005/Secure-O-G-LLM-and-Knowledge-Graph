"""A-442: bare numbers share one frequency key with page counters; the optional position test keeps data that does not
repeat at the same vertical position and still removes real running lines. Default behavior stays byte-identical."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from docling_core.types.doc import DocItemLabel, DoclingDocument, Size, TableCell, TableData

from graph_builder.corpus.chunking import chunk_document
from graph_builder.corpus.config import fingerprint, validate_config
from graph_builder.ingestion.filters import filter_running_lines, positional_repeats
from test_chunking import add_text, make_document, provenance

ROOT = Path(__file__).resolve().parents[1]
PAGES = 6
TOLERANCE = 0.005   # 5 units on the 1000 unit test page; the data below moves by 8 units from page to page


def run(document, tolerance=None):
    result, drops = filter_running_lines(document, .08, .5, 1.0, .5, 3.0, None, tolerance)
    return result, drops


def add_numeric_table(document, page, values, top):
    """A one-row table of bare numbers at ``top``."""
    cells = [TableCell(text=value, bbox=provenance(page, top=top, bottom=top + 10, left=100 + 80 * column, right=150 + 80 * column).bbox,
                       start_row_offset_idx=0, end_row_offset_idx=1, start_col_offset_idx=column, end_col_offset_idx=column + 1)
             for column, value in enumerate(values)]
    return document.add_table(data=TableData(num_rows=1, num_cols=len(values), table_cells=cells),
                              prov=provenance(page, top=top, bottom=top + 10))


def report_document():
    """Running header and footer on every page, a bare page number at the same place, and numeric data cells in the
    bottom margin whose position differs on every page (the defect: they share the key '#' with the page numbers)."""
    document = make_document(PAGES)
    for page in range(1, PAGES + 1):
        add_text(document, "Reference 42", page, 20, 30)
        add_text(document, "Body text of the page.", page, 400, 410)
        add_numeric_table(document, page, ["150", "0", str(page * 7)], top=920 + 8 * page)
        add_text(document, str(page), page, 975, 985, left=290, right=310)
        add_text(document, f"Page {page} of {PAGES}", page, 988, 998)
    return document


def cells_of(result):
    return [[c.text for c in table.data.table_cells] for table in result.tables]


class PositionTests(unittest.TestCase):
    def test_defect_reproduced_without_the_option(self) -> None:
        result, _ = run(report_document())
        self.assertTrue(all(cell == "" for row in cells_of(result) for cell in row), "all numeric cells are removed (the defect)")

    def test_data_cells_are_kept_with_the_option(self) -> None:
        result, _ = run(report_document(), TOLERANCE)
        self.assertEqual([row[:2] for row in cells_of(result)], [["150", "0"]] * PAGES)
        self.assertEqual([row[2] for row in cells_of(result)], [str(page * 7) for page in range(1, PAGES + 1)])

    def test_real_running_lines_are_still_removed(self) -> None:
        off, off_drops = run(report_document())
        on, on_drops = run(report_document(), TOLERANCE)
        self.assertEqual(on_drops, off_drops - PAGES * 3)            # only the numeric cells of the tables come back
        for result in (off, on):
            self.assertEqual([t.text for t in result.texts if t.text], ["Body text of the page."] * PAGES)

    def test_same_output_when_every_removed_line_repeats_at_one_position(self) -> None:
        document = make_document(PAGES)
        for page in range(1, PAGES + 1):
            add_text(document, "Reference 42", page, 20, 30)
            add_text(document, f"Version Page {page} of {PAGES}", page, 38, 48)
            add_text(document, str(page), page, 960, 970, left=290, right=310)
            add_text(document, "Body", page, 400, 410)
        off, off_drops = run(document)
        on, on_drops = run(document, TOLERANCE)
        self.assertEqual(off_drops, PAGES * 3)
        self.assertEqual((off.model_dump_json(), off_drops), (on.model_dump_json(), on_drops))

    def test_option_off_is_identical_to_not_passing_it(self) -> None:
        document = report_document()
        old, old_drops = filter_running_lines(document, .08, .5, 1.0, .5, 3.0)
        none, none_drops = filter_running_lines(document, .08, .5, 1.0, .5, 3.0, None, None)
        self.assertEqual((old.model_dump_json(), old_drops), (none.model_dump_json(), none_drops))

    def test_table_fragment_header_still_recovers_frequency_with_the_option(self) -> None:
        document = make_document(4)
        for page in range(1, 5):
            add_text(document, "Reference 99", page, 50, 60)
            if page < 4:
                add_text(document, f"Version Page {page} of 4", page, 68, 78, right=260)
            else:
                cells = [TableCell(text=text, bbox=provenance(page, top=68, bottom=78, left=left, right=right).bbox,
                                   start_row_offset_idx=0, end_row_offset_idx=1, start_col_offset_idx=column,
                                   end_col_offset_idx=column + 1)
                         for column, (text, left, right) in enumerate([("Version", 100, 150), ("Page 4 of 4", 170, 260)])]
                document.add_table(data=TableData(num_rows=1, num_cols=2, table_cells=cells), prov=provenance(page))
            add_text(document, "Published May", page, 86, 96)
        result, count = filter_running_lines(document, .08, .5, 1, .5, 3, None, TOLERANCE)
        self.assertEqual(count, 13)
        self.assertTrue(all(not cell.text for cell in result.tables[0].data.table_cells))

    def test_header_table_cells_that_repeat_at_one_position_are_still_removed(self) -> None:
        document = make_document(PAGES)
        for page in range(1, PAGES + 1):
            cells = [TableCell(text=text, bbox=provenance(page, top=top, bottom=top + 10).bbox, start_row_offset_idx=row,
                               end_row_offset_idx=row + 1, start_col_offset_idx=0, end_col_offset_idx=1)
                     for row, (text, top) in enumerate([("Ref. GRG-10230", 20), (f"Page {page} of {PAGES}", 34)])]
            document.add_table(data=TableData(num_rows=2, num_cols=1, table_cells=cells), prov=provenance(page, top=20, bottom=44))
            add_text(document, "Body", page, 400, 410)
        for tolerance in (None, TOLERANCE):
            result, _ = run(document, tolerance)
            self.assertTrue(all(not cell for row in cells_of(result) for cell in row), tolerance)

    def test_sparse_text_counter_keeps_the_legacy_decision(self) -> None:
        """DR-09: positional protection is restricted to cells; converter-only text must not be rescued."""
        document = make_document(PAGES)
        for page in range(1, PAGES + 1):
            add_text(document, "Body", page, 400, 410)
            add_text(document, str(page * 3 + 100), page, 300 + 7 * page, 310 + 7 * page)   # other numbers keep '#' frequent
            if page % 3 == 0:
                add_text(document, str(page), page, 970, 980)
        off, _ = run(document)
        on, _ = run(document, TOLERANCE)
        self.assertEqual(sum(t.text in ("3", "6") for t in off.texts), 0)
        self.assertEqual(sum(t.text in ("3", "6") for t in on.texts), 0)

    def test_rescued_cell_does_not_rescue_adjacent_text_in_the_running_block(self) -> None:
        document = make_document(PAGES)
        for page in range(1, PAGES + 1):
            # A varying table-cell anchor in the margin; an adjacent text item is outside the margin.
            add_numeric_table(document, page, ["150"], top=930 + 2 * page)
            add_text(document, "3", page, 919, 929, left=100, right=110)
            add_text(document, str(page), page, 980, 990)
        off, _ = run(document)
        on, _ = run(document, 0.001)
        self.assertEqual([t.text for t in off.texts], [t.text for t in on.texts])
        self.assertTrue(all(row == ["150"] for row in cells_of(on)))
        self.assertTrue(all(row == [""] for row in cells_of(off)))

    def test_mixed_logical_line_cannot_rescue_its_text_fragment(self) -> None:
        document = make_document(PAGES)
        for page in range(1, PAGES + 1):
            top = 930 + 4 * page
            add_numeric_table(document, page, ["150"], top=top)
            add_text(document, "3", page, top, top + 10, left=155, right=165)
            add_text(document, str(page), page, 980, 990)
        off, _ = run(document)
        on, _ = run(document, 0.001)
        self.assertEqual([t.text for t in off.texts], [t.text for t in on.texts])
        self.assertTrue(all(row == ["150"] for row in cells_of(on)))

    def test_real_table_data_repeated_at_the_same_position_remains_a_limit(self) -> None:
        document = make_document(PAGES)
        for page in range(1, PAGES + 1):
            add_numeric_table(document, page, ["150"], top=940)
        self.assertEqual(cells_of(run(document, TOLERANCE)[0]), [[""]] * PAGES)

    def test_positional_repeats_counts_distinct_pages_and_applies_the_window(self) -> None:
        document = make_document(4)
        box = provenance(1, top=500, bottom=510).bbox

        def occurrence(key, page, top):
            return {"key": key, "boxes": {page: [box.model_copy(update={"t": top, "b": top + 10})]}}
        # centres: page 1 twice at 0.505, page 2 at 0.515, page 3 at 0.535 (0.020 from page 2), plus an empty key
        occurrences = [occurrence("#", 1, 500), occurrence("#", 1, 500), occurrence("#", 2, 510), occurrence("#", 3, 530),
                       occurrence("", 4, 500)]
        pages = document.pages
        self.assertEqual(positional_repeats(occurrences, pages, 0.011, 3), set())     # never 3 distinct pages in reach
        self.assertEqual(positional_repeats(occurrences, pages, 0.011, 2), {(0, 1), (1, 1), (2, 2)})   # page 3 is 0.020 away
        self.assertEqual(positional_repeats(occurrences, pages, 0.0195, 3), set())
        self.assertEqual(positional_repeats(occurrences, pages, 0.0205, 3), {(2, 2)})  # only page 2 reaches both neighbours
        self.assertNotIn((4, 4), positional_repeats(occurrences, pages, 0.5, 1))       # an empty key never repeats

    def test_page_size_does_not_matter(self) -> None:
        """The position is a fraction of the page height: the same layout on a smaller page gives the same result."""
        document = DoclingDocument(name="small")
        for page in range(1, PAGES + 1):
            document.add_page(page_no=page, size=Size(width=300, height=500))
        for page in range(1, PAGES + 1):
            for text, top in ((f"Page {page} of {PAGES}", 8), (str(page), 20)):
                document.add_text(label=DocItemLabel.TEXT, text=text, prov=provenance(page, text, top, top + 5, left=100, right=150))
            add_numeric_table(document, page, ["150"], top=462 + 4 * page - 4)
        self.assertEqual([row[0] for row in cells_of(run(document)[0])], [""] * PAGES)
        self.assertEqual([row[0] for row in cells_of(run(document, 0.005)[0])], ["150"] * PAGES)


class PositionConfigTests(unittest.TestCase):
    @staticmethod
    def settings(tolerance=None) -> dict:
        config = json.loads((ROOT / "configs" / "corpus" / "default.json").read_text(encoding="utf-8"))
        if tolerance is not None:
            config["filters"]["running_line_position_tolerance"] = tolerance
        return config

    def test_default_configuration_has_no_option_and_the_fingerprint_changes_with_it(self) -> None:
        config = validate_config(self.settings())
        self.assertNotIn("running_line_position_tolerance", config["filters"])
        self.assertNotEqual(fingerprint(config, {}), fingerprint(validate_config(self.settings(TOLERANCE)), {}))
        self.assertNotEqual(fingerprint(validate_config(self.settings(0.01)), {}), fingerprint(validate_config(self.settings(0.02)), {}))

    def test_invalid_values_are_rejected_and_valid_ones_accepted(self) -> None:
        for bad in (0, -0.1, 0.6, "0.02", True, None, [0.02]):
            with self.assertRaises(ValueError, msg=repr(bad)):
                config = self.settings()
                config["filters"]["running_line_position_tolerance"] = bad
                validate_config(config)
        for good in (0.005, 0.02, 0.5, 1e-3):
            validate_config(self.settings(good))

    def test_chunks_keep_the_data_with_the_option_and_default_chunks_are_unchanged(self) -> None:
        def text(config) -> str:
            chunks, _, _ = chunk_document(report_document(), "sample", config, set())
            return "\n".join(chunk["text"] for chunk in chunks)
        off, on = text(self.settings()), text(self.settings(TOLERANCE))
        self.assertNotIn("150", off)
        self.assertIn("150", on)
        self.assertIn("Body text of the page.", off)
        for running in ("Reference 42", "Page 1 of 6"):
            self.assertNotIn(running, off)
            self.assertNotIn(running, on)
        self.assertEqual(text(self.settings()), text(copy.deepcopy(self.settings())))

    def test_shared_default_configuration_file_is_not_changed_by_the_option(self) -> None:
        default = json.loads((ROOT / "configs" / "corpus" / "default.json").read_text(encoding="utf-8"))
        self.assertNotIn("running_line_position_tolerance", default["filters"])


if __name__ == "__main__":
    unittest.main()
