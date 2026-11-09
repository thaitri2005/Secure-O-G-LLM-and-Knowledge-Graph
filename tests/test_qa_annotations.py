"""A-414: 'N records not printed' annotation detection on synthetic layouts (no PDF needed)."""
import unittest

from graph_builder.corpus.qa import annotations as ann
from graph_builder.corpus.qa.ledger import build_table
from graph_builder.corpus.qa.signals import CheckContext, Registry

CONFIG = ann.load_config()


def line(text: str, x: float, top: float, height: float = 9.0, char_w: float = 4.5) -> list[dict]:
    """Words of one text line starting at x; a word is char_w wide per character, words 2.2 pt apart."""
    words, cursor = [], x
    for token in text.split():
        width = len(token) * char_w
        words.append({"text": token, "bbox": [cursor, top, cursor + width, top + height]})
        cursor += width + 2.2
    return words


def hits_of(words: list[dict], parts: list[dict] | None = None) -> list[dict]:
    return ann.analyse_page(ann.build_segments(words, CONFIG), parts or [], CONFIG)


class DetectionTest(unittest.TestCase):
    def test_left_of_title_plural(self):
        hits = hits_of(line("3 records not printed", 42, 224) + line("Operations Summary", 260, 224))
        self.assertEqual([(h["count"], h["family"], h["title"]["relation"]) for h in hits], [(3, "operations_summary", "same_line")])

    def test_singular_and_comma_count(self):
        self.assertEqual(hits_of(line("1 record not printed", 42, 100))[0]["count"], 1)
        self.assertEqual(hits_of(line("1,250 records not printed", 42, 100))[0]["count"], 1250)

    def test_right_of_title_parenthesised(self):
        hits = hits_of(line("Surveys", 477, 605) + line("(1 not shown)", 500, 605))
        self.assertEqual([(h["count"], h["family"], h["pattern"]) for h in hits], [(1, "surveys", "n_not_shown")])

    def test_title_on_line_above(self):
        hits = hits_of(line("Mud Reports", 260, 200) + line("6 records not printed", 42, 214))
        self.assertEqual(hits[0]["family"], "mud_reports")
        self.assertEqual(hits[0]["title"]["relation"], "above")

    def test_footer_without_title_is_found_with_unknown_family(self):
        hits = hits_of(line("2 records not printed", 42, 760))
        self.assertEqual((hits[0]["count"], hits[0]["family"]), (2, "other_or_unknown"))

    def test_deterministic(self):
        words = line("3 records not printed", 42, 224) + line("Operations Summary", 260, 224) + line("Surveys (1 not shown)", 400, 500)
        self.assertEqual(hits_of(words), hits_of(list(reversed(words))))


class NegativeTest(unittest.TestCase):
    def test_prose_is_rejected(self):
        prose = "The operator said that 3 records not printed were later recovered from the archive"
        self.assertEqual(hits_of(line(prose, 40, 300)), [])

    def test_printed_footers_page_numbers_and_missing_count(self):
        for text in ("Printed on 12-Mar-19", "Page 3 of 5 printed", "records not printed", "Report not printed", "Report No: 3", "12 records printed"):
            self.assertEqual(hits_of(line(text, 42, 760)), [], text)

    def test_digits_in_other_text(self):
        self.assertEqual(hits_of(line("Depth 1,000 ft 3 records", 42, 300) + line("not printed", 300, 330)), [])

    def test_empty_page(self):
        self.assertEqual(hits_of([]), [])


class TableMatchTest(unittest.TestCase):
    words = line("3 records not printed", 42, 224) + line("Operations Summary", 260, 224)

    def test_table_below_matches(self):
        hits = hits_of(self.words, [{"table_id": "t1", "bbox": [48, 233, 573, 300]}])
        self.assertEqual((hits[0]["table"]["table_id"], hits[0]["table"]["kind"]), ("t1", "below"))

    def test_far_table_or_other_column_does_not_match(self):
        self.assertIsNone(hits_of(self.words, [{"table_id": "t1", "bbox": [48, 400, 573, 500]}])[0]["table"])
        self.assertIsNone(hits_of(self.words, [{"table_id": "t2", "bbox": [300, 233, 573, 300]}])[0]["table"])

    def test_table_above_does_not_match(self):
        self.assertIsNone(hits_of(self.words, [{"table_id": "t1", "bbox": [48, 100, 573, 200]}])[0]["table"])

    def test_nearest_table_wins(self):
        hits = hits_of(self.words, [{"table_id": "b", "bbox": [48, 250, 573, 300]}, {"table_id": "a", "bbox": [48, 235, 573, 300]}])
        self.assertEqual(hits[0]["table"]["table_id"], "a")

    def test_text_fallback_without_geometry(self):
        hits = ann.analyse_page(ann.segments_from_text("Mud Reports\n 4 records   not printed \nother"), [], CONFIG)
        self.assertEqual((hits[0]["count"], hits[0]["bbox"], hits[0]["table"]), (4, None, None))


class LedgerCompletenessTest(unittest.TestCase):
    def test_signal_sets_partial_in_source_and_default_stays_unknown(self):
        registry = Registry()
        registry.register_reason(*ann.REASONS[0])
        calls = {"hit": True}
        registry.register_check("fake", lambda ctx, ent: [registry.signal(ann.CODE, "table", ent["ids"], evidence={"count": 1})] if calls["hit"] else [], "table", "1")
        context = CheckContext(registry, {}, ".", {}, validator={"status": "pass"})
        table = {"table_id": "t", "parts": []}
        file_row = {"file_id": "f"}
        self.assertEqual(build_table(context, file_row, table)["completeness"], "PARTIAL_IN_SOURCE")
        calls["hit"] = False
        self.assertEqual(build_table(context, file_row, table)["completeness"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
