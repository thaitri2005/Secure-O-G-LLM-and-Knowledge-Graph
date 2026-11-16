"""C-03c: a text cut off with a trailing ellipsis (``... ``) is read as a table-of-contents dotted-leader line and removed from the
chunks, which silently drops data (a report cell truncated by the producing software). The optional
``filters.toc_leader_min_dots`` makes a run of fewer dots a leader only when a page number follows it. Default stays byte-identical."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from docling_core.types.doc import DocItemLabel

from graph_builder.corpus.chunking import chunk_document
from graph_builder.corpus.config import fingerprint, validate_config
from graph_builder.ingestion.filters import dropped_item_reasons, has_toc_leader
from test_chunking import add_text, make_document

ROOT = Path(__file__).resolve().parents[1]
SENTENCE = 'Rig was 95% cleared off location at 18:00 hrs. Still need to top off 24 ft of 5-1/2" X ...'
LEADER = "Drilling summary " + "." * 58 + " 4"


def document_with(*texts: str):
    document = make_document(1)
    items = [add_text(document, text, 1, 100 + 30 * index, 110 + 30 * index) for index, text in enumerate(texts)]
    return document, items


class HasTocLeaderTests(unittest.TestCase):
    def test_default_keeps_the_old_rule_for_any_run_of_three_dots(self) -> None:
        for text in ("cut off ...", "cut off ... 12", "Chapter " + "." * 20 + " 4", "Chapter .... ", "a...\nb"):
            self.assertTrue(has_toc_leader(text), text)
            self.assertTrue(has_toc_leader(text, None), text)
        for text in ("no dots", "a.. b", "x ... y", "", "end of sentence."):
            self.assertFalse(has_toc_leader(text), text)

    def test_short_run_without_page_number_is_not_a_leader_with_the_option(self) -> None:
        for text in (SENTENCE, "wait on cement ...", "cut off....", "a ...\nb ..."):
            self.assertFalse(has_toc_leader(text, 5), text)

    def test_bare_dots_without_any_letter_or_digit_stay_leader_fragments(self) -> None:
        for text in ("...", " ... ", "......", "...."):
            self.assertTrue(has_toc_leader(text, 5), text)

    def test_page_number_after_a_short_run_still_makes_a_leader(self) -> None:
        for text in ("Introduction ... 5", "Introduction .... 12", "1. Scope ....  7\n"):
            self.assertTrue(has_toc_leader(text, 5), text)

    def test_long_run_is_a_leader_with_or_without_a_page_number(self) -> None:
        for text in (LEADER, "Chapter " + "." * 5, "Chapter " + "." * 40 + "  "):
            self.assertTrue(has_toc_leader(text, 5), text)

    def test_one_leader_line_among_several_decides(self) -> None:
        self.assertTrue(has_toc_leader("first ...\nsecond ........ 9", 5))
        self.assertFalse(has_toc_leader("first ...\nsecond ....", 5))


class ExclusionTests(unittest.TestCase):
    def test_default_excludes_the_truncated_sentence_and_the_option_keeps_it(self) -> None:
        document, (sentence, leader) = document_with(SENTENCE, LEADER)
        off = dropped_item_reasons(document)
        on = dropped_item_reasons(document, 5)
        self.assertEqual(off[sentence.self_ref], "dotted_leader_toc")
        self.assertEqual(off[leader.self_ref], "dotted_leader_toc")
        self.assertNotIn(sentence.self_ref, on)
        self.assertEqual(on[leader.self_ref], "dotted_leader_toc")

    def test_option_none_is_identical_to_not_passing_it(self) -> None:
        document, _ = document_with(SENTENCE, LEADER, "Plain sentence.")
        self.assertEqual(dropped_item_reasons(document), dropped_item_reasons(document, None))

    def test_toc_heading_detection_still_follows_the_remaining_leaders(self) -> None:
        document = make_document(1)
        heading = add_text(document, "Table of Contents", 1, 50, 60, label=DocItemLabel.SECTION_HEADER)
        add_text(document, LEADER, 1, 100, 110)
        on = dropped_item_reasons(document, 5)
        self.assertEqual(on[heading.self_ref], "document_index_heading")

    def test_heading_on_a_page_with_only_ellipsis_lines_is_no_toc_heading_with_the_option(self) -> None:
        document = make_document(1)
        heading = add_text(document, "Contents", 1, 50, 60, label=DocItemLabel.SECTION_HEADER)
        add_text(document, SENTENCE, 1, 100, 110)
        self.assertIn(heading.self_ref, dropped_item_reasons(document))      # old behavior: the ellipsis line makes the page a TOC page
        self.assertNotIn(heading.self_ref, dropped_item_reasons(document, 5))


class ChunkingConfigTests(unittest.TestCase):
    @staticmethod
    def settings(minimum=None) -> dict:
        config = json.loads((ROOT / "configs" / "corpus" / "default.json").read_text(encoding="utf-8"))
        if minimum is not None:
            config["filters"]["toc_leader_min_dots"] = minimum
        return config

    @staticmethod
    def text(config) -> str:
        document, _ = document_with(SENTENCE, LEADER, "Plain sentence.")
        chunks, _, stats = chunk_document(document, "sample", config, set())
        return "\n".join(chunk["text"] for chunk in chunks) + "|" + json.dumps(stats["dropped"], sort_keys=True)

    def test_chunks_keep_the_truncated_sentence_only_with_the_option(self) -> None:
        off, on = self.text(self.settings()), self.text(validate_config(self.settings(5)))
        self.assertNotIn("cleared off", off)
        self.assertIn("cleared off location", on)
        self.assertIn("Plain sentence.", off)
        self.assertNotIn("Drilling summary", off + on)                       # the real leader line stays excluded either way
        self.assertIn('"dotted_leader_toc": 2', off)
        self.assertIn('"dotted_leader_toc": 1', on)

    def test_default_is_deterministic_and_unchanged_by_validation(self) -> None:
        self.assertEqual(self.text(self.settings()), self.text(validate_config(self.settings())))

    def test_default_has_no_option_and_the_fingerprint_changes_with_it(self) -> None:
        config = validate_config(self.settings())
        self.assertNotIn("toc_leader_min_dots", config["filters"])
        self.assertNotEqual(fingerprint(config, {}), fingerprint(validate_config(self.settings(5)), {}))
        self.assertNotEqual(fingerprint(validate_config(self.settings(5)), {}), fingerprint(validate_config(self.settings(6)), {}))

    def test_invalid_values_are_rejected_and_valid_ones_accepted(self) -> None:
        for bad in (0, 1, 3, -5, 101, 5.5, "5", True, None, [5]):
            with self.assertRaises(ValueError, msg=repr(bad)):
                config = self.settings()
                config["filters"]["toc_leader_min_dots"] = bad
                validate_config(config)
        for good in (4, 5, 20, 100):
            validate_config(self.settings(good))

    def test_shared_default_configuration_files_are_not_changed_by_the_option(self) -> None:
        for name in ("default.json", "k1.json"):
            raw = json.loads((ROOT / "configs" / "corpus" / name).read_text(encoding="utf-8-sig"))
            self.assertNotIn("toc_leader_min_dots", raw.get("filters", {}))


if __name__ == "__main__":
    unittest.main()
