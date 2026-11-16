"""Producer-side quarantine (``chunking.quarantine``): visibility, value-before-label, chunk join, OFF identity, configuration.
Synthetic text layers and documents; no PDF is read."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import unittest
from graph_builder.corpus.chunking import chunk_document
from graph_builder.corpus.config import load_config, validate_config
from graph_builder.corpus.quarantine import (INFORMATIONAL, MARKING_DEFAULT, _scan_page, _value_before_label, chunk_reasons, chunk_sidecar,
                                             dropped_items, empty_report, mark_quarantine, quarantine_settings, visibility)
from test_chunking import add_text, make_document
ROOT = Path(__file__).resolve().parents[1]
SETTINGS = quarantine_settings({"scan_visibility": True, "scan_value_before_label": True, "list_page_status": True, "mark_review": True})
def word(text, left, right, top=100.0, row=0):
    return {"text": text, "bbox": [left, top, right, top + 10], "row": row}
def layer(words, text=""):
    return {"page": 1, "width": 600.0, "height": 800.0, "rotation": 0, "upright_for_pairing": False, "chars": [], "words": words,
            "rulings": [], "text": text or " ".join(w["text"] for w in words), "provenance": "synthetic"}
def scan(words, items, raw="", settings=SETTINGS, claimed=frozenset()):
    report = empty_report(settings)
    _scan_page(layer(words, raw), items, settings, claimed, report)
    return report
def item(ref, text, left, right, top=100.0):
    return {"ref": ref, "text": text, "boxes": [[left, top, right, top + 10]]}
def reasons(report):
    return sorted(f["reason"] for f in report["findings"])
class VisibilityTests(unittest.TestCase):
    RAW = frozenset({"Field", "Hot", "Springs", "Bay", "Valley", "Type", "Casing"})
    def test_fully_visible_item_has_no_finding(self):
        r = visibility("Field: Hot Springs", ["Field:", "Hot", "Springs"], self.RAW, frozenset({"Field", "Hot", "Springs"}))
        self.assertEqual(r, {"tail": [], "whole": [], "elsewhere": [], "absent": []})
    def test_clipped_tail_of_a_word_is_a_tail_not_hidden_text(self):
        r = visibility("Bay Valley", ["Bay", "Va"], self.RAW, frozenset({"Bay", "Va"}))
        self.assertEqual((r["tail"], r["whole"], r["absent"]), (["Valley"], [], []))
    def test_word_in_text_layer_but_visible_nowhere_is_hidden(self):
        r = visibility("Original Well Bore Type:", ["Original", "Well", "Bore"], self.RAW | {"Original", "Well", "Bore"},
                       frozenset({"Original", "Well", "Bore"}))
        self.assertEqual((r["whole"], r["elsewhere"], r["absent"]), (["Type"], [], []))
    def test_word_visible_elsewhere_on_the_page_is_displaced_not_hidden(self):
        r = visibility("Well Casing", ["Well"], self.RAW | {"Well"}, frozenset({"Well", "Casing"}))
        self.assertEqual((r["whole"], r["elsewhere"]), ([], ["Casing"]))
    def test_word_not_in_the_text_layer_at_all_is_absent(self):
        r = visibility("Well Zzz", ["Well"], frozenset({"Well"}), frozenset({"Well"}))
        self.assertEqual((r["whole"], r["absent"]), ([], ["Zzz"]))
    def test_other_segmentation_of_the_same_letters_is_visible(self):
        r = visibility("760-341-0186", ["760-", "341-0186"], frozenset({"7603410186"}), frozenset({"760", "3410186"}))
        self.assertEqual((r["whole"], r["absent"], r["tail"]), ([], [], []))
    def test_punctuation_only_difference_is_visible(self):
        r = visibility("Dull:", ["Dull"], frozenset({"Dull"}), frozenset({"Dull"}))
        self.assertEqual(sum(map(len, r.values())), 0)
class ScanPageTests(unittest.TestCase):
    def test_hidden_label_is_reported_and_tail_is_informational(self):
        words = [word("Well", 10, 30), word("Bore:", 32, 60), word("Field:", 100, 130), word("Va", 132, 145)]
        raw = "Well Bore: Type: Field: Valley"
        report = scan(words, [item("#/texts/0", "Well Bore: Type:", 10, 60), item("#/texts/1", "Field: Valley", 100, 145)], raw)
        found = {f["item"]: f["reason"] for f in report["findings"]}
        self.assertEqual(found, {"#/texts/0": "text_not_visible", "#/texts/1": "text_tail_clipped"})
        self.assertIn("text_tail_clipped", INFORMATIONAL)
        self.assertNotIn("text_tail_clipped", MARKING_DEFAULT)
    def test_visible_page_has_no_finding(self):
        words = [word("Name:", 10, 40), word("Ann", 45, 65)]
        self.assertEqual(scan(words, [item("#/texts/0", "Name: Ann", 10, 65)])["findings"], [])
class ValueBeforeLabelTests(unittest.TestCase):
    def row(self):
        # Name: | Chris Hoffman ..... Title: | Owner       (item = "Chris Hoffman Title:")
        return [word("Name:", 10, 40), word("Chris", 45, 75), word("Hoffman", 78, 120), word("Title:", 170, 200), word("Owner", 205, 240)]
    def test_value_in_front_of_the_next_label_is_found(self):
        report = scan(self.row(), [item("#/texts/0", "Chris Hoffman Title:", 45, 200)])
        self.assertEqual(reasons(report), ["value_before_label"])
        details = report["findings"][0]["details"]
        self.assertEqual((details["value_words"], details["label"], details["previous_label"]), (["Chris", "Hoffman"], "Title:", "Name:"))
    def test_item_that_starts_with_its_label_is_not_reported(self):
        report = scan(self.row(), [item("#/texts/0", "Name: Chris Hoffman", 10, 120)])
        self.assertEqual(reasons(report), [])
    def test_list_number_without_label_to_the_left_is_not_reported(self):
        words = [word("10.1.", 10, 30), word("Scope", 70, 100), word("of:", 102, 115)]  # column gap but no label word to the left
        self.assertEqual(reasons(scan(words, [item("#/texts/0", "10.1. Scope of:", 10, 115)])), [])
    def test_ordinary_phrase_label_without_column_gap_is_not_reported(self):
        words = [word("Name:", 10, 40), word("Total", 43, 63), word("Depth", 66, 90), word("(ft):", 93, 110)]
        self.assertEqual(reasons(scan(words, [item("#/texts/0", "Total Depth (ft):", 43, 110)])), [])
    def test_items_already_claimed_by_label_value_are_not_reported_twice(self):
        report = scan(self.row(), [item("#/texts/0", "Chris Hoffman Title:", 45, 200)], claimed=frozenset({"#/texts/0"}))
        self.assertEqual(reasons(report), [])
    def test_label_in_the_middle_of_a_row_of_different_height_lines_uses_overlap(self):
        words = [word("Name:", 10, 40, top=104.0, row=1), word("Chris", 45, 75, top=100.0, row=0), word("Hoffman", 78, 120, top=100.0, row=0),
                 word("Title:", 170, 200, top=103.0, row=2)]
        self.assertIsNotNone(_value_before_label(layer(words), [1, 2, 3], 1.5))
class ChunkJoinTests(unittest.TestCase):
    CHUNKS = [{"chunk_id": "f:s1:c0", "type": "text", "text": "Well Bore: Type:\nWeight:", "pages": [1]},
              {"chunk_id": "f:s1:c1", "type": "text", "text": "other", "pages": [1]},
              {"chunk_id": "f:s1:c2", "type": "text", "text": "elsewhere", "pages": [2]},
              {"chunk_id": "f:t1:c0", "type": "table", "text": "| a |", "pages": [1]}]
    def report(self):
        return {"findings": [{"page": 1, "reason": "text_not_visible", "text": "Well Bore: Type:", "item": "#/texts/0", "details": {}},
                             {"page": 2, "reason": "text_tail_clipped", "text": "no such text", "item": "#/texts/9", "details": {}}],
                "findings_total": 2, "pages": [{"page": 1, "status": "few_label_cells", "colon_items": 2},
                                              {"page": 2, "status": "grid_supported", "colon_items": 3}]}
    def test_finding_maps_to_the_chunk_that_contains_the_item_text(self):
        mapping, stats = chunk_reasons(self.CHUNKS, self.report(), None)
        self.assertEqual(mapping[0], ["page_unexamined:few_label_cells", "text_not_visible"])
        self.assertEqual(mapping[1], ["page_unexamined:few_label_cells"])
        self.assertEqual((stats["mapped_by_text"], stats["mapped_by_page"]), (1, 1))
    def test_review_marks_only_findings_never_page_status_or_informational(self):
        chunks = copy.deepcopy(self.CHUNKS)
        for c in chunks:
            c["quality"] = "ok"
        mark_quarantine(chunks, {"quarantine": self.report()}, SETTINGS)
        self.assertEqual([c["quality"] for c in chunks], ["review", "ok", "ok", "ok"])
    def test_text_not_in_layer_is_informational_and_does_not_mark(self):
        chunks = copy.deepcopy(self.CHUNKS)
        for c in chunks:
            c["quality"] = "ok"
        report = self.report()
        report["findings"] = [{"page": 1, "reason": "text_not_in_layer", "text": "Well Bore: Type:", "item": "#/texts/0", "details": {}}]
        mark_quarantine(chunks, {"quarantine": report}, SETTINGS)
        self.assertTrue(all(c["quality"] == "ok" for c in chunks))
        self.assertIn("text_not_in_layer", INFORMATIONAL)
    def test_mark_review_off_changes_nothing(self):
        chunks = copy.deepcopy(self.CHUNKS)
        for c in chunks:
            c["quality"] = "ok"
        mark_quarantine(chunks, {"quarantine": self.report()}, quarantine_settings({"scan_visibility": True}))
        self.assertTrue(all(c["quality"] == "ok" for c in chunks))
    def test_review_reasons_allowlist_can_include_an_informational_reason(self):
        chunks = copy.deepcopy(self.CHUNKS)
        for c in chunks:
            c["quality"] = "ok"
        only = quarantine_settings({"mark_review": True, "review_reasons": ["text_tail_clipped"]})
        report = self.report()
        report["findings"][1]["text"] = "elsewhere"
        mark_quarantine(chunks, {"quarantine": report}, only)
        self.assertEqual([c["quality"] for c in chunks], ["ok", "ok", "review", "ok"])
    def test_sidecar_gives_chunk_ids_reasons_and_classes_for_text_chunks_only(self):
        side = chunk_sidecar({"quarantine": self.report()}, self.CHUNKS)
        self.assertNotIn("f:t1:c0", side["chunks"])
        row = {"reason": "text_not_visible", "class": "hidden_text", "source": "quarantine"}
        self.assertIn(row, side["chunks"]["f:s1:c0"])
    def test_sidecar_includes_label_value_abstentions_by_reason(self):
        stats = {"label_value": {"groups_abstained": 1, "abstentions": [{"page": 1, "reason": "label_item_unmapped", "items": ["#/texts/0"],
                                                                           "texts": ["Well Bore: Type:"]}]}}
        side = chunk_sidecar(stats, self.CHUNKS)
        self.assertEqual(side["chunks"]["f:s1:c0"], [{"reason": "label_item_unmapped", "class": "label_value_abstention", "source": "label_value"}])
class SettingsAndOffIdentityTests(unittest.TestCase):
    def test_defaults_are_all_off(self):
        s = quarantine_settings({})
        for name in ("list_dropped_items", "list_page_status", "scan_visibility", "scan_value_before_label", "mark_review"):
            self.assertIs(s[name], False)
    def test_invalid_settings_are_rejected(self):
        for bad in ({"unknown": 1}, {"mark_review": "yes"}, {"column_gap_factor": -1}, {"review_reasons": []}, {"max_findings": 0}, []):
            with self.assertRaises(ValueError):
                quarantine_settings(bad)
    def test_default_configuration_has_no_quarantine_key(self):
        self.assertNotIn("quarantine", load_config(ROOT / "configs" / "corpus" / "default.json")["chunking"])
        self.assertNotIn("quarantine", json.loads((ROOT / "configs" / "corpus" / "default.json").read_text(encoding="utf-8-sig"))["chunking"])
    def test_configuration_accepts_and_validates_the_key(self):
        config = json.loads((ROOT / "configs" / "corpus" / "default.json").read_text(encoding="utf-8-sig"))
        config["chunking"]["quarantine"] = {"list_dropped_items": True}
        validate_config(copy.deepcopy(config))
        config["chunking"]["quarantine"] = {"bogus": True}
        with self.assertRaises(ValueError):
            validate_config(config)
    def test_chunking_without_the_key_has_no_quarantine_statistics_and_same_chunks(self):
        config = load_config(ROOT / "configs" / "corpus" / "default.json")
        doc = make_document()
        add_text(doc, "Name: Ann", 1)
        chunks, tables, stats = chunk_document(doc, "d", config, set())
        self.assertNotIn("quarantine", stats)
        with_key = copy.deepcopy(config)
        with_key["chunking"]["quarantine"] = {"list_dropped_items": True, "mark_review": True}
        chunks2, tables2, stats2 = chunk_document(doc, "d", with_key, set())
        self.assertEqual(chunks, chunks2)  # the option never changes a chunk (no scan flag, so no finding can mark one)
        self.assertEqual(tables, tables2)
        self.assertIn("quarantine", stats2)
        stats2.pop("quarantine")
        self.assertEqual(stats, stats2)
class LeaderInfoTests(unittest.TestCase):
    def test_long_leader_with_page_number_versus_trailing_ellipsis(self):
        from graph_builder.corpus.quarantine import leader_info
        toc = leader_info("SUMMARY " + "." * 60 + " 3")
        self.assertEqual((toc["leader_dots"], toc["page_number_follows"]), (60, True))
        ellipsis = leader_info("Drill to 716 ft with full returns...")
        self.assertEqual((ellipsis["leader_dots"], ellipsis["page_number_follows"]), (3, False))
        self.assertEqual(leader_info("no leader")["leader_dots"], 0)
class DroppedItemTests(unittest.TestCase):
    def test_toc_item_is_listed_with_text_and_page_and_kept_chunks_are_unchanged(self):
        doc = make_document()
        add_text(doc, "Introduction .......... 5", 1)
        add_text(doc, "Real content", 1)
        config = load_config(ROOT / "configs" / "corpus" / "default.json")
        config["chunking"]["quarantine"] = {"list_dropped_items": True}
        chunks, _, stats = chunk_document(doc, "d", config, set())
        dropped = stats["quarantine"]["dropped_items"]
        self.assertEqual(dropped["by_reason"].get("dotted_leader_toc"), 1)
        self.assertEqual([(row["page"], row["reason"], row["text"]) for row in dropped["listed"]], [(1, "dotted_leader_toc", "Introduction .......... 5")])
        self.assertEqual(stats["dropped"].get("dotted_leader_toc"), 1)
        self.assertNotIn("Introduction", " ".join(c["text"] for c in chunks))
if __name__ == "__main__":
    unittest.main()
