"""Unit tests for deterministic text helpers and span handling."""
from __future__ import annotations
import unittest
import hashlib
from helpers import PROJECT_ROOT, clean_dir
from kgbuilder.core.text import *
from kgbuilder.core.text import _base_form, _canon_number, _date_matches


class TextTest(unittest.TestCase):
    def test_iter_jsonl(self):
        root = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/text_stream")
        path = root / "rows.jsonl"
        rows = [{"id": 1}, {"id": 2}]
        write_jsonl(path, rows)
        stream = iter_jsonl(path)
        self.assertIs(iter(stream), stream)
        self.assertEqual(list(stream), rows)
        path.write_text('\ufeff{"id":1}\n\n{"id":2}\n', encoding="utf-8")
        self.assertEqual(list(iter_jsonl(path)), rows)

    def test_abbreviation_and_sentence_forms(self):
        value = "Harold D. Smith was born in 1950. He died in 2000."
        self.assertEqual([value[a:b] for a, b in split_sentences_abbrev(value)],
                         ["Harold D. Smith was born in 1950.", "He died in 2000."])
        value = "Born Ani Ohev Otach Rosa (translit. I Love You Rosa) in Israel."
        self.assertEqual(split_sentences_abbrev(value), [(0, len(value))])
        self.assertEqual(split_sentences_abbrev("  Dr.\n Smith. ", 10), [(12, 15), (17, 23)])
        for sentence, name in [("It was designed by Robert A. M. Stern and opened.", "Robert A. M. Stern"),
                               ("They played the Studio 3,500 club.", "Studio 3,500"),
                               ("They are African Americans.", "African American")]:
            self.assertTrue(contains_form(sentence_form(sentence), norm_surface(name)))
        self.assertFalse(contains_form(sentence_form("The value is 1610."), "610"))
        self.assertTrue(contains_form(sentence_form("Completed on June 1, 2009."), "2009-06-01"))

    def test_window_grounding_matching_helpers(self):
        value = "completed on June 1, 2009 and opened 2010"
        self.assertEqual(_date_matches(value), [(13, 25, "2009-06-01"), (37, 41, "2010")])
        self.assertEqual(find_dates(value), [iso for _, _, iso in _date_matches(value)])
        self.assertEqual(find_dates(value), ["2009-06-01", "2010"])
        for value, expected in [("3,500", "3500"), ("610.0", "610"), ("17068.8", "17068.8"), ("610.50", "610.50")]:
            self.assertEqual(_canon_number(value), expected)
        for value, expected in [("610_(metres)", "610"), ("610.0", "610"), ("17068.8", "17068.8"),
                                ("610.50", "610.50"), ("Studio 3,500", "studio 3500"),
                                ("Robert A. M. Stern", "robert a.m. stern")]:
            self.assertEqual(norm_surface(value), expected)
        self.assertEqual(_base_form("Studio 3,500 club & Robert A. M. Stern"), "studio 3500 club and robert a.m. stern")
        self.assertEqual(literal_forms('"1_June_2009"'), {"1 june 2009", "2009-06-01"})
        value = "born June 1, 2009 in X"
        self.assertEqual(literal_forms(value), {norm_surface(value)})
        self.assertEqual(literal_forms("Adolfo_Su\u00e1rez_Madrid\u2013Barajas_Airport"), {"adolfo suarez madrid-barajas airport"})
        for value in ("610_(metres)", "610.0"):
            self.assertEqual(literal_forms(value), {"610"})

    def test_window_grounding_numbers_and_verdicts(self):
        for value, expected in [("4th Earl of Strathmore and Kinghorne", {"4"}), ("7Th", {"7"}),
                                ("Henry VIII", {"8"}), ("Louis XIV", {"14"}), ("II IV", {"2", "4"}),
                                ("Apollo 11", {"11"}), ("Two Brides And A Baby", {"2"}),
                                ("first twentieth one twenty", {"1", "20"}), ("Cnut the Great", set()),
                                ("I Love You Rosa", set()), ("Washington DC", set()), ("CD Projekt", set()),
                                ("MD MI CV MIX I V X", set())]:
            self.assertEqual(number_tokens(value), expected)
        for value, expected in [("True", "yes"), ("False. According to the input,", "no"),
                                ("No, that statement is **false**", "no"), ("The statement...", None), (None, None)]:
            self.assertEqual(parse_yes_no(value), expected)
        for value, expected in [("The statement is not supported.", "no"), ("It is supported.", "yes"),
                                ("unsupported", "no"), ("Nothing", None)]:
            self.assertEqual(parse_yes_no(value, extended=True), expected)

    def test_predicates(self):
        self.assertEqual(predicate_words("birthPlace"), "birth place")
        self.assertEqual(predicate_words("works_at"), "works at")
        self.assertEqual(predicate_key("was born in"), "born in")
        self.assertEqual(predicate_key("Works_On"), "works on")
        self.assertEqual(predicate_redundancy(["works on", "works_on", "is located in", "located in", "born in"]), 0.4)
        self.assertEqual(predicate_redundancy([]), 0.0)

    def test_match_key(self):
        for value, expected in [("Nie_Haisheng", "nie haisheng"),
                                ("People's_Republic_of_China", "people's republic of china"),
                                ('"1 June 2009"', "1 june 2009"),
                                ("Alan Turing", surface_key("Alan Turing")), ('"', '"')]:
            with self.subTest(value=value):
                self.assertEqual(match_key(value), expected)

    def test_normalization_and_ids(self):
        self.assertEqual(surface_key("  IBM\u00a0Research "), "ibm research")
        self.assertEqual(norm_pred("was hired by"), "hired by")
        self.assertEqual(pad("2021"), "2021-01-01")
        self.assertTrue(holds_at("2021", "2024", "2022")); self.assertFalse(holds_at("2021", "2024", "2024"))
    def test_time(self):
        self.assertEqual(extract_time("2024: Alice left Acme Labs and joined Nova AI.", "Nova AI"), "2024")
        self.assertEqual(extract_time("born in Hubei on October 13, 1964.", None), "1964-10-13")
        for text, expected in [("on 2024-02-13", "2024-02-13"), ("in 2024-02", "2024-02"),
                               ("13 October 1964", "1964-10-13"), ("October 1964", "1964-10"),
                               ("in 1964", "1964"), ("undated", None)]:
            with self.subTest(text=text):
                self.assertEqual(extract_time(text, None), expected)
        self.assertEqual(extract_time("1990 Acme and 2024 Nova AI", "Nova AI"), "2024")
        self.assertEqual(extract_time("1990 Acme and 2024 Nova AI", "unknown"), "1990")

    def test_hash_and_json_io(self):
        self.assertEqual(h("a", None, "b"), hashlib.sha1(b"a\x1f\x1fb").hexdigest())
        self.assertNotEqual(h("c", "joined"), h("c", "left"))
        self.assertNotEqual(h("s", "p", "o", "2021"), h("s", "p", "o", "2024"))
        tmp = clean_dir(PROJECT_ROOT / ".cache/tmp/tests/text")
        write_json(tmp / "value.json", {"b": None, "a": "Việt"})
        write_jsonl(tmp / "rows.jsonl", [{"b": 2, "a": 1}, {"text": "Việt"}])
        self.assertEqual(read_jsonl(tmp / "rows.jsonl"), [{"a": 1, "b": 2}, {"text": "Việt"}])
        self.assertEqual(cj({"b": 2, "a": 1}), '{"a":1,"b":2}')
        self.assertEqual(sha256_file(tmp / "value.json"), sha256_text((tmp / "value.json").read_text(encoding="utf-8")))
        self.assertNotIn(b"\r", (tmp / "rows.jsonl").read_bytes())
        self.assertTrue((tmp / "value.json").read_bytes().endswith(b"\n"))
    def test_sentences_and_chunks(self):
        text = "2021: Alice joined Acme Labs.\n2024: Alice left Acme Labs and joined Nova AI."
        self.assertEqual([text[s:e] for s, e in split_sentences(text)], ["2021: Alice joined Acme Labs.", "2024: Alice left Acme Labs and joined Nova AI."])
        long = " ".join(["word"] * 100)
        spans = chunk_spans(long, 50)
        self.assertTrue(all(0 < e - s <= 50 and long[s:e] == long[s:e].strip() for s, e in spans))
        chars = "".join(long[s:e].replace(" ", "") for s, e in spans)
        self.assertEqual(chars, long.replace(" ", ""))
        self.assertEqual(split_sentences("  A.  B. ", 10), [(12, 14), (16, 18)])
        self.assertEqual(chunk_spans("x" * 120, 50), [(0, 50), (50, 100), (100, 120)])
        self.assertEqual(chunk_spans("   \n ", 50), [])


if __name__ == "__main__": unittest.main()
