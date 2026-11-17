"""Label-value re-assembly from cell geometry (``chunking.label_value``): positive, negative, ambiguous and OFF-identity cases
on synthetic text layers (no PDF is read)."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from docling_core.types.doc import DocItemLabel

from graph_builder.corpus.catalog import Corpus
from graph_builder.corpus.chunking import chunk_document
from graph_builder.corpus.config import fingerprint, load_config, validate_config
from graph_builder.corpus.config import fingerprint as make_fingerprint
from graph_builder.corpus.k1_export import export_k1
from graph_builder.corpus.label_value import analyse_page, correct_document, empty_report, label_value_settings
from test_chunking import add_text, make_document
from test_corpus_k1 import K1_CONFIG, PackageCase, add_sample

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = label_value_settings({"min_label_cells": 2})


def word(text, left, right, row=0, top=100.0):
    return {"text": text, "bbox": [left, top, right, top + 10], "row": row}


def vertical_ruling(x):
    return [x - 0.4, 90.0, x + 0.4, 115.0]


def layer(words, rulings=(vertical_ruling(200), vertical_ruling(400))):
    return {"page": 1, "width": 600.0, "height": 1000.0, "rotation": 0, "upright_for_pairing": False, "chars": [],
            "words": list(words), "rulings": list(rulings), "text": "", "provenance": "synthetic"}


def grid_words(value_a="1700", value_b="1", value_c=None):
    """Three cells in one row: Proposed TD (ft): 1700 | Days On Location: 1 | Last BOP Test: (blank)."""
    words = [word("Proposed", 10, 60), word("TD", 62, 75), word("(ft):", 77, 100)]
    words += [word(value_a, 150, 190)] if value_a else []
    words += [word("Days", 210, 235), word("On", 237, 250), word("Location:", 252, 300)]
    words += [word(value_b, 350, 390)] if value_b else []
    words += [word("Last", 410, 430), word("BOP", 432, 455), word("Test:", 457, 485)]
    words += [word(value_c, 520, 560)] if value_c else []
    return words


def item(ref, text, left, right, order, top=100.0):
    return {"ref": ref, "text": text, "order": order, "box": [left, top, right, top + 10]}


def run(layer_, items, settings=SETTINGS):
    report = empty_report(settings)
    rewrites = analyse_page(layer_, items, settings, report)
    return {r["ref"]: r["text"] for r in rewrites}, report


class AssociationTests(unittest.TestCase):
    def gluedPage(self):
        items = [item("#/texts/0", "Proposed TD (ft):", 10, 100, 0),
                 item("#/texts/1", "Days On Location: 1700", 150, 300, 1),
                 item("#/texts/2", "Last BOP Test: 1", 350, 485, 2)]
        return layer(grid_words()), items

    def test_value_glued_to_the_next_label_goes_back_to_its_own_label(self):
        page, items = self.gluedPage()
        rewrites, report = run(page, items)
        self.assertEqual(rewrites, {"#/texts/0": "Proposed TD (ft): 1700", "#/texts/1": "Days On Location: 1",
                                    "#/texts/2": "Last BOP Test:"})
        self.assertEqual((report["groups_changed"], report["groups_abstained"], report["words_moved"]), (1, 0, 2))

    def test_words_are_conserved_across_the_group(self):
        page, items = self.gluedPage()
        rewrites, _ = run(page, items)
        before = sorted(token for it in items for token in it["text"].split())
        after = sorted(token for text in rewrites.values() for token in text.split())
        self.assertEqual(before, after)

    def test_correct_pairs_are_not_touched(self):
        items = [item("#/texts/0", "Proposed TD (ft): 1700", 10, 190, 0), item("#/texts/1", "Days On Location: 1", 210, 390, 1),
                 item("#/texts/2", "Last BOP Test:", 410, 485, 2)]
        rewrites, report = run(layer(grid_words()), items)
        self.assertEqual(rewrites, {})
        self.assertEqual((report["groups_changed"], report["groups_abstained"]), (0, 0))

    def test_value_of_a_blank_cell_moves_to_the_cell_that_owns_it(self):
        words = grid_words(value_a=None, value_b="1700", value_c=None)
        words = [w for w in words if w["text"] != "1700"] + [word("1700", 150, 190)]  # value sits in cell A
        items = [item("#/texts/0", "Proposed TD (ft):", 10, 100, 0), item("#/texts/1", "Days On Location: 1700", 150, 300, 1),
                 item("#/texts/2", "Last BOP Test:", 410, 485, 2)]
        rewrites, _ = run(layer(words), items)
        self.assertEqual(rewrites, {"#/texts/0": "Proposed TD (ft): 1700", "#/texts/1": "Days On Location:"})

    def test_multi_word_and_numeric_values_keep_order_and_units(self):
        words = [word("Hole", 10, 30), word("Made:", 32, 60), word("16", 150, 160), word("/", 162, 165), word("0.5", 167, 190),
                 word("Days:", 210, 240), word("3", 350, 360)]
        items = [item("#/texts/0", "Hole Made:", 10, 60, 0), item("#/texts/1", "Days: 16 / 0.5", 150, 240, 1),
                 item("#/texts/2", "3", 350, 360, 2)]
        rewrites, _ = run(layer(words), items)
        self.assertEqual(rewrites["#/texts/0"], "Hole Made: 16 / 0.5")
        # the value item of the cell of "Days:" is attached to its label and the emptied item is kept as an empty text
        self.assertEqual((rewrites["#/texts/1"], rewrites["#/texts/2"]), ("Days: 3", ""))

    def test_value_only_items_outside_a_corrected_group_are_not_attached(self):
        words = [word("Hole", 10, 30), word("Made:", 32, 60), word("16", 150, 160), word("Days:", 210, 240), word("3", 350, 360)]
        items = [item("#/texts/0", "Hole Made: 16", 10, 160, 0), item("#/texts/1", "Days:", 210, 240, 1), item("#/texts/2", "3", 350, 360, 2)]
        rewrites, _ = run(layer(words), items)
        self.assertEqual(rewrites, {})

    def test_a_separate_value_item_is_attached_after_the_wrong_value_is_removed(self):
        words = [word("Proposed", 10, 60), word("TD:", 62, 80), word("1700", 150, 190), word("Well", 210, 230), word("Bore:", 232, 260),
                 word("Original", 300, 330), word("Well", 332, 350), word("Bore", 352, 372)]
        items = [item("#/texts/0", "Proposed TD:", 10, 80, 0), item("#/texts/1", "Well Bore: 1700", 150, 260, 1),
                 item("#/texts/2", "Original Well Bore", 300, 372, 2)]
        rewrites, report = run(layer(words), items)
        self.assertEqual(rewrites, {"#/texts/0": "Proposed TD: 1700", "#/texts/1": "Well Bore: Original Well Bore", "#/texts/2": ""})
        self.assertEqual(report["words_moved"], 4)

    def test_a_value_item_that_reaches_into_a_neighbouring_cell_gives_up_only_the_words_of_the_label_cell(self):
        words = [word("Proposed", 10, 60), word("TD:", 62, 80), word("1700", 150, 190), word("Well", 210, 230), word("Bore:", 232, 260),
                 word("Original", 300, 330), word("Well", 332, 350), word("Bore", 352, 372), word("AFE", 410, 430), word("No.", 432, 450)]
        items = [item("#/texts/0", "Proposed TD:", 10, 80, 0), item("#/texts/1", "Well Bore: 1700", 150, 260, 1),
                 item("#/texts/2", "Original Well Bore AFE No.", 300, 450, 2)]
        rewrites, _ = run(layer(words), items)
        self.assertEqual(rewrites, {"#/texts/0": "Proposed TD: 1700", "#/texts/1": "Well Bore: Original Well Bore", "#/texts/2": "AFE No."})

    def test_a_value_item_whose_remaining_words_would_be_reordered_is_not_split(self):
        words = [word("Proposed", 10, 60), word("TD:", 62, 80), word("1700", 150, 190), word("Well", 210, 230), word("Bore:", 232, 260),
                 word("Original", 300, 330), word("AFE", 410, 430), word("No.", 432, 450)]
        items = [item("#/texts/0", "Proposed TD:", 10, 80, 0), item("#/texts/1", "Well Bore: 1700", 150, 260, 1),
                 item("#/texts/2", "No. Original AFE", 300, 450, 2)]
        rewrites, report = run(layer(words), items)
        self.assertEqual(rewrites, {})
        self.assertEqual(report["abstentions"][0]["reason"], "value_item_order")

    def test_item_box_smaller_than_its_text_is_mapped_through_the_text_line(self):
        words = [word("Operator:", 10, 60), word("City", 100, 120), word("of", 122, 130), word("Akutan", 132, 170),
                 word("Rig:", 210, 230), word("Major", 350, 380), word("LF90", 382, 400)]
        items = [item("#/texts/0", "Operator:", 10, 60, 0), item("#/texts/1", "Rig: City of Akutan Major LF90", 100, 230, 1)]
        rewrites, _ = run(layer(words), items)
        self.assertEqual(rewrites, {"#/texts/0": "Operator: City of Akutan", "#/texts/1": "Rig: Major LF90"})

    def test_an_item_with_two_labels_is_rebuilt_in_reading_order(self):
        words = [word("Operator:", 10, 60), word("City", 100, 120), word("of", 122, 130), word("Akutan", 132, 170),
                 word("Rig:", 210, 230), word("Major", 350, 380), word("LF90", 382, 400), word("Spud", 410, 430), word("Date:", 432, 460)]
        items = [item("#/texts/0", "Operator:", 10, 60, 0), item("#/texts/1", "Rig: City of Akutan Spud Date: Major LF90", 100, 460, 1)]
        rewrites, _ = run(layer(words), items)
        self.assertEqual(rewrites, {"#/texts/0": "Operator: City of Akutan", "#/texts/1": "Rig: Major LF90 Spud Date:"})


class AbstentionTests(unittest.TestCase):
    def test_cell_with_two_labels_keeps_the_text_and_records_the_reason(self):
        # cell B holds two labels, so nothing can be said about which of them owns a value: keep every text
        words = [w for w in grid_words() if w["text"] != "1"] + [word("Other:", 310, 340)]
        items = [item("#/texts/0", "Proposed TD (ft):", 10, 100, 0), item("#/texts/1", "Days On Location: 1700", 150, 300, 1)]
        rewrites, report = run(layer(words), items)
        self.assertEqual(rewrites, {})
        self.assertEqual(report["groups_abstained"], 1)
        self.assertEqual(report["abstentions"][0]["reason"], "cell_multiple_labels")

    def test_token_from_a_cell_without_label_is_not_moved(self):
        words = [word("Proposed", 10, 60), word("TD:", 62, 80), word("Days", 210, 235), word("On:", 237, 250), word("7", 450, 470)]
        rewrites, report = run(layer(words), [item("#/texts/0", "Days On: 7", 210, 470, 0)])
        self.assertEqual(rewrites, {})
        self.assertEqual(report["abstentions"][0]["reason"], "token_in_unlabelled_cell")

    def test_item_whose_text_differs_from_the_pdf_words_is_not_examined(self):
        items = [item("#/texts/0", "Proposed TD (ft):", 10, 100, 0), item("#/texts/1", "Days On Location 1700 extra", 150, 300, 1)]
        rewrites, report = run(layer(grid_words()), items)
        self.assertEqual(rewrites, {})
        self.assertEqual(report["groups_abstained"], 0)

    def test_equal_words_in_two_cells_are_moved_by_position_not_by_text(self):
        words = [word("A:", 10, 30), word("5", 150, 160), word("B:", 210, 230), word("5", 350, 360)]
        items = [item("#/texts/0", "A:", 10, 30, 0), item("#/texts/1", "B: 5 5", 150, 360, 1)]
        rewrites, report = run(layer(words), items)
        self.assertEqual(rewrites, {"#/texts/0": "A: 5", "#/texts/1": "B: 5"})
        self.assertEqual(report["groups_abstained"], 0)

    def test_a_row_where_the_text_line_is_ambiguous_is_not_mapped(self):
        # the item box misses its second '0'; the line has three '0': the line mapping needs equal counts and refuses
        words = [word("A:", 10, 30), word("0", 150, 160), word("B:", 210, 230), word("0", 350, 360), word("0", 365, 375)]
        items = [item("#/texts/0", "A:", 10, 30, 0), item("#/texts/1", "B: 0", 210, 230, 1)]
        rewrites, report = run(layer(words), items)
        self.assertEqual(rewrites, {})
        self.assertEqual(report["items_with_colon_unmapped"], 1)

    def test_an_unmapped_item_with_a_label_like_word_is_reported_and_one_without_is_not(self):
        words = [word("A:", 10, 30), word("0", 150, 160), word("B:", 210, 230), word("0", 350, 360), word("0", 365, 375)]
        rewrites, report = run(layer(words), [item("#/texts/0", "A:", 10, 30, 0), item("#/texts/1", "B: 0", 210, 230, 1)])
        self.assertEqual(rewrites, {})
        self.assertEqual([(a["reason"], a["items"]) for a in report["abstentions"]], [("label_item_unmapped", ["#/texts/1"])])
        rewrites, report = run(layer(words), [item("#/texts/0", "A:", 10, 30, 0), item("#/texts/1", "B 0 extra", 210, 230, 1)])
        self.assertEqual((rewrites, report["groups_abstained"], report["items_with_colon_unmapped"]), ({}, 0, 0))

    def orderPage(self):
        """Cells ``Wear: A | Brgs: 0 | Gge: 0`` whose values 0 are separate items; the item of the labels carries the value A last."""
        words = [word("Wear:", 10, 40), word("A", 150, 160), word("Brgs:", 210, 240), word("0", 350, 360), word("Gge:", 410, 440), word("0", 550, 560)]
        boxes = [[10, 100, 40, 110], [150, 100, 160, 110], [210, 100, 240, 110], [410, 100, 440, 110]]
        return layer(words), [{"ref": "#/texts/0", "text": "", "order": 0, "boxes": boxes, "box": [10, 100, 440, 110]},
                              item("#/texts/1", "0", 350, 360, 1), item("#/texts/2", "0", 550, 560, 2)]

    def test_an_item_whose_word_order_differs_from_its_cells_is_kept_and_reported(self):
        page, items = self.orderPage()
        items[0]["text"] = "Wear: Brgs: Gge: A"
        rewrites, report = run(page, items)
        self.assertEqual(rewrites, {})
        self.assertEqual(len(report["abstentions"]), 1)
        found = report["abstentions"][0]  # the separate value items of the group are listed with it, the text of none is changed
        self.assertEqual((found["reason"], found["items"][0], found["texts"][0]), ("item_order_differs_from_cells", "#/texts/0", "Wear: Brgs: Gge: A"))
        self.assertEqual(found["details"][0]["word"], "Brgs:")
        self.assertEqual((report["groups_changed"], report["words_moved"]), (0, 0))

    def test_an_item_in_cell_order_is_not_reported(self):
        page, items = self.orderPage()
        items[0]["text"] = "Wear: A Brgs: Gge:"
        rewrites, report = run(page, items)
        self.assertEqual((rewrites, report["groups_abstained"], report["abstentions"]), ({}, 0, []))

    def test_page_with_few_label_cells_is_unsupported_and_untouched(self):
        words = [word("Note:", 10, 40), word("see", 50, 70), word("x", 80, 90)]
        rewrites, report = run(layer(words, rulings=()), [item("#/texts/0", "Note: see x", 10, 90, 0)])
        self.assertEqual(rewrites, {})
        self.assertEqual(report["pages_skipped"], {"few_label_cells": 1})

    def test_narrative_colons_without_rulings_are_untouched(self):
        words = [word("See", 10, 30), word("http://example.org/a:b", 32, 140), word("Main[3]:Up", 150, 200)]
        rewrites, report = run(layer(words, rulings=()), [item("#/texts/0", "See http://example.org/a:b Main[3]:Up", 10, 200, 0)],
                               label_value_settings({"min_label_cells": 1}))
        self.assertEqual(rewrites, {})
        self.assertEqual(report["groups_abstained"], 0)

    def test_determinism(self):
        page, items = AssociationTests().gluedPage()
        first = run(page, copy.deepcopy(items))
        second = run(copy.deepcopy(page), copy.deepcopy(items))
        self.assertEqual(first[0], second[0])
        self.assertEqual(json.dumps(first[1], sort_keys=True), json.dumps(second[1], sort_keys=True))


class FakePdf:
    rotation = 0

    def __init__(self, path):
        pass

    def __getitem__(self, index):
        outer = self
        return type("Page", (), {"get_rotation": lambda self: outer.rotation})()

    def close(self):
        pass


def glued_document():
    document = make_document(1)
    for text, left, right in (("Proposed TD (ft):", 10, 100), ("Days On Location: 1700", 150, 300), ("Last BOP Test: 1", 350, 485)):
        add_text(document, text, top=100, bottom=110, left=left, right=right)
    return document


def config():
    value = json.loads((ROOT / "configs/corpus/default.json").read_text(encoding="utf-8"))
    value["ocr"] = {"engine": "easyocr", "languages": ["en"], "model_size": "small", "scale": 2.5, "confidence_threshold": 0.5}
    return value


class DocumentTests(unittest.TestCase):
    def chunks(self, document, **options):
        settings = config()
        if options:
            settings["chunking"]["label_value"] = {"min_label_cells": 2, **options}
        with patch("graph_builder.corpus.label_value.source_page", return_value=layer(grid_words())), \
                patch("pypdfium2.PdfDocument", FakePdf):
            return chunk_document(document, "doc", validate_config(settings), set(), Path("synthetic.pdf"))

    def test_option_on_rewrites_text_boxes_and_reports_the_pdf_words(self):
        document = glued_document()
        before = document.export_to_dict()
        chunks, _, statistics = self.chunks(document, box_expansions_pt=[0.5])
        self.assertEqual(before, document.export_to_dict())  # the input document is not modified
        self.assertEqual(chunks[0]["text"], "Proposed TD (ft): 1700\nDays On Location: 1\nLast BOP Test:")
        report = statistics["label_value"]
        self.assertEqual((report["items_changed"], report["groups_abstained"]), (3, 0))
        moved = report["changes"][1]
        self.assertEqual((moved["old"], moved["text"]), ("Days On Location: 1700", "Days On Location: 1"))
        self.assertEqual(moved["moved_out"], [{"text": "1700", "box": [150.0, 100.0, 190.0, 110.0]}])
        self.assertEqual(moved["moved_in"][0]["text"], "1")

    def test_item_made_of_several_text_runs_is_mapped_by_all_its_boxes(self):
        from docling_core.types.doc import ProvenanceItem
        from test_chunking import provenance
        document = make_document(1)
        add_text(document, "Proposed TD (ft):", top=100, bottom=110, left=10, right=100)
        glued = add_text(document, "Days On Location: 1700", top=100, bottom=110, left=210, right=300)
        glued.prov[0] = ProvenanceItem(page_no=1, bbox=glued.prov[0].bbox, charspan=(0, 17))
        glued.prov.append(ProvenanceItem(page_no=1, bbox=provenance(1, top=100, bottom=110, left=150, right=190).bbox, charspan=(18, 22)))
        add_text(document, "Last BOP Test: 1", top=100, bottom=110, left=350, right=485)
        chunks, _, statistics = self.chunks(document, box_expansions_pt=[0.5])
        self.assertEqual(chunks[0]["text"], "Proposed TD (ft): 1700\nDays On Location: 1\nLast BOP Test:")
        self.assertEqual(statistics["label_value"]["items_not_examined"], {})

    def test_item_spanning_two_pages_is_counted_not_examined(self):
        from docling_core.types.doc import ProvenanceItem
        from test_chunking import provenance
        document = make_document(2)
        item = add_text(document, "Days On Location: 1700", top=100, bottom=110, left=150, right=300)
        item.prov.append(ProvenanceItem(page_no=2, bbox=provenance(2, top=100, bottom=110).bbox, charspan=(10, 22)))
        with patch("graph_builder.corpus.label_value.source_page", return_value=layer(grid_words())), patch("pypdfium2.PdfDocument", FakePdf):
            _, report = correct_document(document, Path("x.pdf"), SETTINGS, set())
        self.assertEqual(report["items_not_examined"], {"spans_pages": 1})

    def test_items_excluded_as_dotted_leader_lines_are_not_used_and_corrected_text_cannot_become_excluded(self):
        words = [word("A:", 10, 30), word("B:", 210, 230), word("5", 350, 360), word("...", 365, 380), word("7", 385, 395)]
        document = make_document(1)
        for text, left, right in (("A:", 10, 30), ("B: 5", 210, 360), ("... 7", 365, 395)):
            add_text(document, text, top=100, bottom=110, left=left, right=right)
        settings = config()
        settings["chunking"]["label_value"] = {"min_label_cells": 2, "box_expansions_pt": [0.5]}
        with patch("graph_builder.corpus.label_value.source_page", return_value=layer(words)), patch("pypdfium2.PdfDocument", FakePdf):
            chunks, _, statistics = chunk_document(document, "doc", validate_config(settings), set(), Path("x.pdf"))
        self.assertEqual(chunks[0]["text"], "A:\nB: 5")
        self.assertEqual(statistics["dropped"].get("running_line", 0), 0)
        self.assertEqual(statistics["label_value"]["items_changed"], 0)

    def test_option_off_is_identical_to_the_old_behaviour(self):
        chunks, _, statistics = self.chunks(glued_document())
        self.assertEqual(chunks[0]["text"], "Proposed TD (ft):\nDays On Location: 1700\nLast BOP Test: 1")
        self.assertNotIn("label_value", statistics)

    def test_chunk_ids_and_count_do_not_change(self):
        off, _, _ = self.chunks(glued_document())
        on, _, _ = self.chunks(glued_document(), box_expansions_pt=[0.5])
        self.assertEqual([c["chunk_id"] for c in off], [c["chunk_id"] for c in on])
        self.assertEqual([(c["section_path"], c["pages"]) for c in off], [(c["section_path"], c["pages"]) for c in on])

    def test_rotated_ocr_and_missing_source_pages_are_skipped_with_a_reason(self):
        with patch("graph_builder.corpus.label_value.source_page", return_value=layer(grid_words())):
            with patch("pypdfium2.PdfDocument", type("Rotated", (FakePdf,), {"rotation": 90})):
                new, report = correct_document(glued_document(), Path("x.pdf"), SETTINGS, set())
            self.assertEqual(report["pages_skipped"], {"rotated_page": 1})
            with patch("pypdfium2.PdfDocument", FakePdf):
                _, report = correct_document(glued_document(), Path("x.pdf"), SETTINGS, {1})
            self.assertEqual(report["pages_skipped"], {"ocr_page": 1})
        _, report = correct_document(glued_document(), None, SETTINGS, set())
        self.assertEqual(report["error"], "no_source_pdf")

    def test_page_error_isolates_the_page(self):
        with patch("graph_builder.corpus.label_value.source_page", side_effect=RuntimeError("boom")), \
                patch("pypdfium2.PdfDocument", FakePdf):
            _, report = correct_document(glued_document(), Path("x.pdf"), SETTINGS, set())
        self.assertEqual(report["pages_skipped"], {"page_error": 1})
        self.assertEqual(report["items_changed"], 0)

    def test_page_size_mismatch_is_skipped(self):
        small = dict(layer(grid_words()), height=900.0)
        with patch("graph_builder.corpus.label_value.source_page", return_value=small), patch("pypdfium2.PdfDocument", FakePdf):
            _, report = correct_document(glued_document(), Path("x.pdf"), SETTINGS, set())
        self.assertEqual(report["pages_skipped"], {"page_size_mismatch": 1})

    def test_labels_outside_the_configured_list_are_not_candidates(self):
        document = make_document(1)
        for text, left, right in (("Proposed TD (ft):", 10, 100), ("Days On Location: 1700", 150, 300)):
            add_text(document, text, top=100, bottom=110, left=left, right=right, label=DocItemLabel.SECTION_HEADER)
        with patch("graph_builder.corpus.label_value.source_page", return_value=layer(grid_words())), patch("pypdfium2.PdfDocument", FakePdf):
            _, report = correct_document(document, Path("x.pdf"), SETTINGS, set())
        self.assertEqual((report["pages_examined"], report["items_changed"]), (0, 0))


class ExportTests(PackageCase):
    def test_findings_reach_the_export_result_only_when_the_option_is_on_and_the_package_is_the_same_shape(self):
        add_sample(self.corpus, self.root, "sample-report", self.fingerprint)
        off = export_k1(self.corpus, "off", Path("models"), K1_CONFIG)
        self.assertNotIn("label_value", off)
        settings = load_config(ROOT / "configs/corpus/default.json")
        settings["chunking"]["label_value"] = {}
        corpus = Corpus.create(self.root / "on", settings)
        add_sample(corpus, self.root, "sample-report", make_fingerprint(corpus.config, {}))
        on = export_k1(corpus, "on", Path("models"), K1_CONFIG)
        self.assertEqual(on["label_value"]["sample-report"]["method"], "cell_geometry_v1")
        self.assertEqual(on["label_value"]["sample-report"]["items_changed"], 0)
        for group in ("files", "pages", "tables", "forms", "parents", "chunks"):
            self.assertEqual(off[group], on[group], group)
        released = Path(on["export"]) / "chunks.jsonl"
        self.assertEqual(released.read_bytes(), (Path(off["export"]) / "chunks.jsonl").read_bytes())


class ConfigTests(unittest.TestCase):
    def test_default_configuration_has_no_option_and_the_fingerprint_changes_with_it(self):
        off = validate_config(config())
        self.assertNotIn("label_value", off["chunking"])
        self.assertNotIn("label_value", json.loads((ROOT / "configs/corpus/default.json").read_text(encoding="utf-8"))["chunking"])
        on = config()
        on["chunking"]["label_value"] = {}
        self.assertNotEqual(fingerprint(off, {}), fingerprint(validate_config(on), {}))
        on["chunking"]["label_value"] = {"min_label_cells": 6}
        self.assertNotEqual(fingerprint(validate_config(on), {}), fingerprint(validate_config(dict(on, chunking=dict(on["chunking"], label_value={}))), {}))

    def test_invalid_values_are_rejected(self):
        for bad in (True, [], {"unknown": 1}, {"min_label_cells": 0}, {"box_expansions_pt": []}, {"box_expansions_pt": [-1]},
                    {"item_labels": []}, {"max_findings": 0}):
            settings = config()
            settings["chunking"]["label_value"] = bad
            with self.assertRaises(ValueError, msg=repr(bad)):
                validate_config(settings)


def row_page(words, rulings=(vertical_ruling(300), vertical_ruling(450))):
    """One form row whose first cell (x < 300) holds several labels; two more cells with one label each keep the page supported."""
    return layer(list(words) + [word("Date:", 310, 340), word("1", 420, 430), word("Time:", 460, 490), word("5", 560, 570)], rulings)


def shifted_row():
    """PDF row ``Oper: 2 Cont: 7 Serv: 8`` in one cell; the converter glued every value to the NEXT label (``2 Cont:``, ``7 Serv:``)."""
    words = [word("Oper:", 10, 40), word("2", 60, 70), word("Cont:", 80, 110), word("7", 130, 140), word("Serv:", 150, 180), word("8", 230, 240)]
    items = [item("#/texts/0", "Oper:", 10, 40, 0), item("#/texts/1", "2 Cont:", 60, 110, 1), item("#/texts/2", "7 Serv:", 130, 180, 2),
             item("#/texts/3", "8", 230, 240, 3)]
    return row_page(words), items


class ResolutionTests(unittest.TestCase):
    """C-01c options: split_label_cells, rebuild_item_order, review_unverified (all off by default)."""

    def test_defaults_are_off_and_the_row_with_several_labels_stays_silent(self):
        self.assertEqual([label_value_settings({})[k] for k in ("split_label_cells", "rebuild_item_order", "review_unverified")], [False] * 3)
        page, items = shifted_row()
        rewrites, report = run(page, items)
        self.assertEqual((rewrites, report["groups_abstained"], report["abstentions"]), ({}, 0, []))  # the gap C-01c closes

    def test_split_label_cells_gives_every_value_to_its_label(self):
        page, items = shifted_row()
        rewrites, report = run(page, items, label_value_settings({"min_label_cells": 2, "split_label_cells": True}))
        self.assertEqual(rewrites, {"#/texts/0": "Oper: 2", "#/texts/1": "Cont: 7", "#/texts/2": "Serv: 8", "#/texts/3": ""})
        self.assertEqual((report["groups_changed"], report["groups_abstained"]), (1, 0))
        before = sorted(t for i in items for t in i["text"].split())
        self.assertEqual(before, sorted(t for text in rewrites.values() for t in text.split()))  # nothing added or lost

    def test_split_does_not_change_which_pages_are_examined(self):
        words = [word("Oper:", 10, 40), word("2", 60, 70), word("Cont:", 80, 110), word("7", 130, 140)]
        page = layer(words, (vertical_ruling(300),))  # the only cell with labels is the multi-label cell: 0 unsplit label cells
        _, report = run(page, [item("#/texts/0", "Oper:", 10, 40, 0)], label_value_settings({"min_label_cells": 1, "split_label_cells": True}))
        self.assertEqual(report["pages_skipped"], {"few_label_cells": 1})

    def test_cell_with_words_before_the_first_label_or_on_two_rows_is_not_split(self):
        settings = label_value_settings({"min_label_cells": 2, "split_label_cells": True})
        words = [word("5", 10, 20), word("Oper:", 30, 60), word("2", 80, 90), word("Cont:", 100, 130), word("7", 150, 160)]
        rewrites, report = run(row_page(words), [item("#/texts/0", "5 Oper: 2", 10, 90, 0), item("#/texts/1", "Cont: 7", 100, 160, 1)], settings)
        self.assertEqual((rewrites, report["groups_abstained"]), ({}, 0))
        two_rows = [word("Oper:", 10, 40), word("2", 60, 70), word("Cont:", 80, 110, row=1, top=112.0), word("7", 130, 140, row=1, top=112.0)]
        rewrites, report = run(row_page(two_rows), [item("#/texts/0", "Oper: 2", 10, 70, 0)], settings)
        self.assertEqual(rewrites, {})

    def test_split_leaves_a_row_that_is_already_right_alone(self):
        page, _ = shifted_row()
        items = [item("#/texts/0", "Oper: 2 Cont: 7 Serv: 8", 10, 240, 0)]
        rewrites, report = run(page, items, label_value_settings({"min_label_cells": 2, "split_label_cells": True}))
        self.assertEqual((rewrites, report["groups_abstained"]), ({}, 0))

    def test_review_unverified_reports_the_item_that_no_finding_covers(self):
        page, items = shifted_row()
        _, report = run(page, items, label_value_settings({"min_label_cells": 2, "review_unverified": True}))
        # "Oper:" alone says nothing wrong; "2 Cont:" and "7 Serv:" carry the value of the label before them
        self.assertEqual([(a["reason"], a["items"], a["details"][0]["word"]) for a in report["abstentions"]],
                         [("ambiguous_cell_unresolved", ["#/texts/1"], "2"), ("ambiguous_cell_unresolved", ["#/texts/2"], "7")])
        whole = [item("#/texts/0", "Oper: 2 Cont: 7 Serv: 8", 10, 240, 0)]  # every value with its own label: not reported
        _, report = run(page, whole, label_value_settings({"min_label_cells": 2, "review_unverified": True}))
        self.assertEqual(report["abstentions"], [])

    def test_review_reasons_limits_which_abstentions_mark_chunks(self):
        from graph_builder.corpus.label_value import unverified_chunks
        chunks = [{"pages": [1], "text": "A: 1"}, {"pages": [1], "text": "B: 2"}]
        report = {"abstentions": [{"page": 1, "reason": "label_item_unmapped", "items": ["a"], "texts": ["A: 1"]},
                                  {"page": 1, "reason": "cell_multiple_labels", "items": ["b"], "texts": ["B: 2"]}], "groups_abstained": 2}
        self.assertEqual(unverified_chunks(chunks, report)[0], {0, 1})
        self.assertEqual(unverified_chunks(chunks, report, ["cell_multiple_labels"])[0], {1})
        with self.assertRaises(ValueError):
            label_value_settings({"review_reasons": []})

    def test_rebuild_item_order_puts_the_values_next_to_their_labels(self):
        page, items = AbstentionTests().orderPage()
        items[0]["text"] = "Wear: Brgs: Gge: A"
        rewrites, report = run(page, items, label_value_settings({"min_label_cells": 2, "rebuild_item_order": True}))
        self.assertEqual(rewrites, {"#/texts/0": "Wear: A Brgs: 0 Gge: 0", "#/texts/1": "", "#/texts/2": ""})
        self.assertEqual((report["groups_changed"], report["groups_abstained"]), (1, 0))

    def test_rebuild_item_order_keeps_an_item_that_is_in_cell_order_and_one_with_foreign_words(self):
        settings = label_value_settings({"min_label_cells": 2, "rebuild_item_order": True})
        page, items = AbstentionTests().orderPage()
        items[0]["text"] = "Wear: A Brgs: Gge:"
        self.assertEqual(run(page, items, settings)[0], {})
        words = [word("Wear:", 10, 40), word("A", 150, 160), word("Brgs:", 210, 240), word("0", 350, 360), word("Gge:", 410, 440), word("x", 550, 560)]
        items = [{"ref": "#/texts/0", "text": "Wear: Brgs: Gge: A x", "order": 0, "boxes": [[10, 100, 40, 110], [150, 100, 160, 110], [210, 100, 240, 110], [410, 100, 440, 110],
                                                                                    [550, 100, 560, 110]], "box": [10, 100, 560, 110]}]
        rewrites, report = run(layer(words, (vertical_ruling(200), vertical_ruling(400), vertical_ruling(500))), items, settings)
        self.assertEqual((rewrites, report["abstentions"][0]["reason"]), ({}, "token_in_unlabelled_cell"))  # a word in a cell without label: unchanged, reported

    def test_unverified_chunks_map_abstentions_to_the_chunks_that_hold_the_item(self):
        from graph_builder.corpus.label_value import mark_unverified, unverified_chunks
        chunks = [{"pages": [1], "text": "Field: X\nWear: Brgs: Gge: A\n0", "quality": "ok"}, {"pages": [1], "text": "other text", "quality": "ok"},
                  {"pages": [2], "text": "Wear: Brgs: Gge: A", "quality": "ok"}]
        report = {"abstentions": [{"page": 1, "reason": "item_order_differs_from_cells", "items": ["a", "b"], "texts": ["Wear:  Brgs: Gge: A", "0"]}], "groups_abstained": 1}
        marked, stats = unverified_chunks(chunks, report)
        self.assertEqual((marked, stats["groups_marked_by_page"], stats["list_truncated"]), ({0}, 0, False))  # page 2 and the unrelated chunk are not marked
        report["abstentions"][0]["texts"] = ["no such text:"]
        marked, stats = unverified_chunks(chunks, report)
        self.assertEqual((marked, stats["groups_marked_by_page"]), ({0, 1}, 1))  # not found: every chunk of that page
        report["groups_abstained"] = 5  # the list was cut at max_findings
        marked, stats = unverified_chunks(chunks, report)
        self.assertEqual((marked, stats["list_truncated"]), ({0, 1, 2}, True))
        statistics = {"label_value": {"abstentions": [], "groups_abstained": 0}}
        mark_unverified(chunks, statistics, label_value_settings({"review_unverified": True}))
        self.assertEqual([c["quality"] for c in chunks], ["ok"] * 3)
        self.assertEqual(statistics["label_value"]["review"]["chunks"], 0)
        statistics = {"label_value": report | {"groups_abstained": 1, "abstentions": [{"page": 2, "reason": "x", "items": ["a"], "texts": ["Wear: Brgs: Gge: A"]}]}}
        mark_unverified(chunks, statistics, label_value_settings({}))  # option off: untouched, no statistics added
        self.assertEqual(([c["quality"] for c in chunks], "review" in statistics["label_value"]), (["ok"] * 3, False))
        mark_unverified(chunks, statistics, label_value_settings({"review_unverified": True}))
        self.assertEqual([c["quality"] for c in chunks], ["ok", "ok", "review"])
        mark_unverified(chunks, {"label_value": {"skipped": "not_paginated"}}, label_value_settings({"review_unverified": True}))

    def test_options_are_validated_and_in_the_report_settings(self):
        for name in ("split_label_cells", "rebuild_item_order", "review_unverified"):
            with self.assertRaises(ValueError):
                label_value_settings({name: 1})
        self.assertTrue(label_value_settings({"review_unverified": True})["review_unverified"])

    def test_determinism_with_all_options(self):
        settings = label_value_settings({"min_label_cells": 2, "split_label_cells": True, "rebuild_item_order": True, "review_unverified": True})
        page, items = shifted_row()
        first, second = run(page, copy.deepcopy(items), settings), run(copy.deepcopy(page), copy.deepcopy(items), settings)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
