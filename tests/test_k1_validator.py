"""K1 version 0: the corpus chunks pass, and each rule catches the mistake it is for."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("validate_k1", ROOT / "platform" / "validate_k1.py")
validate_k1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate_k1)

TEXT = {"chunk_id": "ak3#c0002", "doc_id": "ak3", "page": 2, "type": "text", "text": "Drilled to 1,955 feet.",
        "section": "Executive Summary", "table_id": None, "row_start": None, "row_end": None}
TABLE = {"chunk_id": "ak3#c0013", "doc_id": "ak3", "page": 8, "type": "table", "text": "| 7-1/2 | 5-1/2 | 221.7 |",
         "section": None, "table_id": "ak3#t004", "row_start": 1, "row_end": 3}


def problems(*rows):
    return validate_k1.check_rows(list(enumerate(rows, start=1)))


class K1ValidatorTests(unittest.TestCase):
    def test_corpus_chunks_pass(self):
        rows = list(validate_k1.read_jsonl(validate_k1.DEFAULT))
        self.assertEqual(len(rows), 372)
        self.assertEqual(validate_k1.check_rows(rows), [])

    def test_good_rows_pass(self):
        self.assertEqual(problems(TEXT, TABLE), [])

    def test_missing_text_fails(self):
        row = copy.deepcopy(TEXT)
        del row["text"]
        self.assertIn("'text' is a required property", problems(row)[0][2])

    def test_duplicate_chunk_id_fails(self):
        self.assertIn("duplicate chunk_id", problems(TEXT, TEXT)[0][2])

    def test_chunk_id_must_match_doc_id(self):
        row = dict(TEXT, doc_id="other")
        self.assertIn("does not start with its doc_id", problems(row)[0][2])

    def test_table_chunk_needs_table_fields(self):
        row = dict(TABLE, table_id=None)
        self.assertTrue(problems(row))

    def test_text_chunk_has_no_rows(self):
        row = dict(TEXT, row_start=1, row_end=2)
        self.assertTrue(problems(row))

    def test_rows_in_order(self):
        row = dict(TABLE, row_start=5, row_end=2)
        self.assertIn("row_end 2 is before row_start 5", problems(row)[0][2])

    def test_page_is_first_of_pages(self):
        row = dict(TEXT, pages=[3, 4])
        self.assertIn("is not the first of pages", problems(row)[0][2])

    def test_line_that_is_not_json_fails(self):
        self.assertTrue(problems("not JSON: broken"))


if __name__ == "__main__":
    unittest.main()
