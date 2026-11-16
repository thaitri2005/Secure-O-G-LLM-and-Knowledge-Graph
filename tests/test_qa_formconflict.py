"""A-435: optional form-versus-text-chunk conflict check (release only). The 'Days On Location: 1700' pairing must be flagged, correct pairs not."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import unittest

from graph_builder.corpus.qa import formconflict as fc
from graph_builder.corpus.qa.signals import Registry

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / "data" / "interim" / "overnight" / "b3" / "a435" / "test-tmp-fc"
FIELDS = [{"key": "Days On Location:", "value": "1"}, {"key": "Proposed TD (ft):", "value": "1,700"}, {"key": "Last BOP Test:", "value": ""},
          {"key": "Operator:", "value": "City of Akutan"}, {"key": "Operator:", "value": "2 / 0"}, {"key": "Rig:", "value": "Major LF90"}]


class PureComparisonTests(unittest.TestCase):
    def test_wrong_pairing_is_flagged_and_correct_pairs_are_not(self) -> None:
        found, compared = fc.conflicts_of(FIELDS, "Proposed TD (ft): 1700\nDays On Location: 1700\nRig: Major LF90")
        self.assertEqual(compared, 3)
        self.assertEqual([(c["label"], c["text_value"], c["form_values"]) for c in found], [("days on location", "1700", ["1"])])
        self.assertEqual(fc.conflicts_of(FIELDS, "Days On Location: 1\nProposed TD (ft): 1700")[0], [])

    def test_text_value_for_a_blank_form_field_is_a_conflict(self) -> None:
        found, _ = fc.conflicts_of(FIELDS, "Last BOP Test: 1")
        self.assertEqual(found, [{"label": "last bop test", "text_value": "1", "form_values": [], "form_blank": True}])

    def test_label_alone_on_its_line_is_not_judged(self) -> None:
        self.assertEqual(fc.conflicts_of(FIELDS, "Days On Location:\n1700\nLast BOP Test:"), ([], 0))

    def test_label_with_several_form_values_accepts_any_of_them(self) -> None:
        self.assertEqual(fc.conflicts_of(FIELDS, "Operator: 2 / 0")[0], [])
        self.assertEqual(fc.conflicts_of(FIELDS, "Operator: City of Akutan")[0], [])
        self.assertEqual(len(fc.conflicts_of(FIELDS, "Operator: Major")[0]), 1)

    def test_value_glued_to_the_wrong_label_is_flagged(self) -> None:
        found, _ = fc.conflicts_of(FIELDS, "Rig: City of Akutan Major LF90")
        self.assertEqual([c["label"] for c in found], ["rig"])

    def test_unknown_labels_are_ignored_and_thousands_separators_fold(self) -> None:
        self.assertEqual(fc.conflicts_of(FIELDS, "Depth: 99\nProposed TD (ft): 1,700"), ([], 1))

    def test_deterministic(self) -> None:
        text = "Rig: City of Akutan Major LF90\nDays On Location: 1700"
        self.assertEqual(fc.conflicts_of(FIELDS, text), fc.conflicts_of(FIELDS, text))


class ReleaseStateTests(unittest.TestCase):
    def setUp(self) -> None:
        shutil.rmtree(SCRATCH, ignore_errors=True)
        SCRATCH.mkdir(parents=True)
        rows = {
            "forms.jsonl": [{"form_id": "f1:f1", "file_id": "f1", "page": 1, "verified": True, "fields": FIELDS},
                            {"form_id": "f1:f2", "file_id": "f1", "page": 2, "verified": False, "fields": FIELDS}],
            "chunks.jsonl": [
                {"chunk_id": "f1:s1:c0", "file_id": "f1", "page": 1, "pages": [1], "type": "text", "text": "Days On Location: 1700", "table_id": None, "form_id": None},
                {"chunk_id": "f1:s2:c0", "file_id": "f1", "page": 1, "pages": [1], "type": "text", "text": "Days On Location: 1", "table_id": None, "form_id": None},
                {"chunk_id": "f1:t1:c0", "file_id": "f1", "page": 1, "pages": [1], "type": "table", "text": "Days On Location: 7", "table_id": "t1", "form_id": None},
                {"chunk_id": "f1:f1", "file_id": "f1", "page": 1, "pages": [1], "type": "form", "text": "Days On Location: 7", "table_id": None, "form_id": "f1:f1"},
                {"chunk_id": "f1:s3:c0", "file_id": "f1", "page": 2, "pages": [2], "type": "text", "text": "Days On Location: 1700", "table_id": None, "form_id": None}]}
        for name, lines in rows.items():
            (SCRATCH / name).write_text("".join(json.dumps(row) + "\n" for row in lines), encoding="utf-8", newline="\n")

    def tearDown(self) -> None:
        shutil.rmtree(SCRATCH, ignore_errors=True)

    def test_only_text_chunks_of_pages_with_a_verified_form_are_compared(self) -> None:
        state = fc.FormConflictState(SCRATCH)
        result = state.analyse("f1", 1)
        self.assertEqual(result["compared_pairs"], 2)
        self.assertEqual([(c["chunk_id"], c["label"]) for c in result["conflicts"]], [("f1:s1:c0", "days on location")])
        self.assertIsNone(state.analyse("f1", 2))       # unverified form: not a reference
        self.assertIsNone(state.analyse("f1", 3))

    def test_check_emits_one_page_signal_with_evidence(self) -> None:
        registry = fc.register_form_conflict(Registry(), ROOT / "configs/qa/form_conflict.json")
        check = next(c for c in registry.checks if c.name == fc.CHECK_NAME)
        context = type("Context", (), {"release_dir": SCRATCH})()
        signals = check.function(context, {"ids": {"file_id": "f1", "page": 1}})
        self.assertEqual([s["code"] for s in signals], ["FORM_TEXT_PAIR_CONFLICT"])
        self.assertEqual(signals[0]["evidence"]["conflict_pairs"], 1)
        self.assertEqual(check.function(context, {"ids": {"file_id": "f1", "page": 2}}), [])


if __name__ == "__main__":
    unittest.main()
