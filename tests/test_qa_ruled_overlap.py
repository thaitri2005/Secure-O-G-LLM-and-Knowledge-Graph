from collections import defaultdict
import unittest

from graph_builder.corpus.qa.cell_evidence import FRAME
from graph_builder.corpus.qa.ruled_overlap import RuledOverlap, RuledPanel, native_targets


FIRST = {"r": 3, "c": 1, "text": "8.45", "bbox": [74, 57, 92, 63]}
SECOND = {"r": 3, "c": 2, "text": "9.05", "bbox": [111, 57, 129, 63]}
NATIVE = {"r": 1, "c": 1, "row_span": 1, "col_span": 2, "text": "8.45 9.05", "bbox": [71, 56, 133, 64],
          "bbox_frame": FRAME, "method": "docling_region", "is_header": False, "status": "review",
          "observed_text": "8.45 9.05", "reason": "native_box_spans_source_columns"}


class RuledOverlapTests(unittest.TestCase):
    def setUp(self):
        self.panel = RuledPanel("source", [65, 38, 140, 85], {}, [FIRST, SECOND])
        self.table = {"table_id": "native", "cells": [NATIVE]}

    def test_mixed_native_cell_uses_two_source_columns_and_preserves_neighbor(self):
        plan = native_targets(self.table, [NATIVE], [self.panel], 1)
        slots, evidence = plan[0]
        self.assertEqual(slots, {(1, 1), (1, 2)})
        self.assertEqual(evidence["action"], "prefer_source_rows_and_columns")
        self.assertEqual(evidence["source_cells"], [[3, 1], [3, 2]])
        overlap = RuledOverlap.__new__(RuledOverlap)
        overlap.replacements, overlap.findings = {}, defaultdict(list)
        chunk = {"chunk_id": "native:c0", "file_id": "file", "page": 1, "row_start": 1, "row_end": 2}
        text = "| Property | A | B | Other |\n| --- | --- | --- | --- |\n| Density | 8.45 9.05 | 8.45 9.05 | 4900 |"
        overlap.project_cells(chunk, text, plan)
        self.assertEqual(overlap.replacements["native:c0"].splitlines()[-1], "| Density | | | 4900 |")
        self.assertEqual(overlap.summary()["ruled_compound_cells_resolved"], 1)

    def test_abstains_for_partial_geometry_unconfirmed_text_or_two_panels(self):
        self.assertFalse(self.panel.source_cells([87, 56, 133, 64], NATIVE["text"]))
        self.assertFalse(self.panel.source_cells([71, 71, 133, 78], NATIVE["text"]))
        self.assertFalse(self.panel.source_cells(NATIVE["bbox"], "8.05 9.45"))
        self.assertFalse(native_targets(self.table, [dict(NATIVE, observed_text="8.05 9.45")], [self.panel], 1))
        other = RuledPanel("other", self.panel.box, {}, [FIRST, SECOND])
        self.assertFalse(native_targets(self.table, [NATIVE], [self.panel, other], 1))
        overlapped = {"table_id": "native", "cells": [NATIVE, dict(NATIVE, c=2, col_span=1)]}
        self.assertFalse(native_targets(overlapped, [NATIVE], [self.panel], 1))

    def test_native_margin_requires_complete_cells_and_independent_text(self):
        wider = dict(NATIVE, bbox=[58, 56, 133, 64])
        self.assertFalse(self.panel.matches(wider["bbox"], wider["text"]))
        (_, proof), = native_targets(self.table, [wider], [self.panel], 1)
        self.assertTrue(proof["native_box_extends_past_panel"])
        self.assertFalse(native_targets(self.table, [dict(wider, observed_text="8.45 9.05 990")], [self.panel], 1))
        self.assertFalse(native_targets(self.table, [dict(wider, bbox=[58, 56, 120, 64])], [self.panel], 1))

    def test_numeric_conflict_masks_only_if_all_literals_are_independently_retained(self):
        cells = [dict(cell, is_header=False, row_span=1, col_span=1) for cell in (FIRST, SECOND)]
        panel = RuledPanel("source", self.panel.box, {}, cells)
        native = dict(NATIVE, col_span=1, bbox=[70, 56, 95, 64], observed_text="8.45")
        table = dict(self.table, cells=[native])
        eligible = {(1, 1)}
        (slots, proof), = native_targets(table, [native], [panel], 1, numeric_conflicts=eligible)
        self.assertEqual(slots, eligible)
        self.assertEqual(proof["action"], "remove_uncertain_numeric_duplicate")
        self.assertFalse(native_targets(table, [native], [panel], 1))
        self.assertFalse(native_targets(table, [native], [RuledPanel("other", panel.box, {}, cells[:1])], 1,
                                        numeric_conflicts=eligible))
        self.assertFalse(native_targets(table, [native], [panel, panel], 1, numeric_conflicts=eligible))
