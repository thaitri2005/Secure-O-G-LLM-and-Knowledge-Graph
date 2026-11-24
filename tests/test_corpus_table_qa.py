"""QA reports unsupported layout and over-budget chunks at the page that owns them."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pymupdf
from tokenizers import Tokenizer, models, pre_tokenizers

from graph_builder.corpus.qa.builtin_checks import check_table_coverage
from graph_builder.corpus.qa.ledger import default_registry, read_release
from graph_builder.corpus.qa.signals import CheckContext
from graph_builder.corpus.report_context import report_context_fallback
from graph_builder.corpus.store import atomic_write_jsonl


class TrackAOutputTests(unittest.TestCase):
    def test_report_context_keeps_ambiguous_day_unresolved_until_given_source_evidence(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "header.pdf"
            with pymupdf.open() as pdf:
                for day, spud in (("11/02/2020", "10/30/2020"), ("11/03/2020", "11/01/2020")):
                    page = pdf.new_page()
                    page.insert_text((50, 40), f"RPT DATE: {day}")
                    page.insert_text((50, 60), "WELL NAME: Test Well 2")
                    page.insert_text((50, 80), f"SPUD DATE: {spud}")
                pdf.save(path)
            pages = [{"page": page, "mode": "text"} for page in (1, 2)]
            resolved = report_context_fallback(path, pages, [1, 2])
            self.assertEqual([resolved[p]["report_date"] for p in (1, 2)], ["2020-11-02", "2020-11-03"])
            self.assertEqual(report_context_fallback(path, pages, [2]), {})
            self.assertEqual(report_context_fallback(path, pages, [1, 2], stacked_pages={2}).keys(), {1})

    def test_over_budget_cell_rows_have_numeric_evidence_without_mutating_chunk(self):
        tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0, "oil": 1, "mud": 2}, unk_token="[UNK]"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        with TemporaryDirectory() as directory:
            release = Path(directory)
            for group in ("files", "pages", "tables", "parents"):
                atomic_write_jsonl(release / f"{group}.jsonl", [])
            chunk = {"chunk_id": "c", "file_id": "f", "parent_id": "t", "table_id": "t", "page": 3,
                     "type": "table", "text": "oil mud oil", "quality": "ok", "row_start": 5, "row_end": 6}
            atomic_write_jsonl(release / "chunks.jsonl", [chunk])
            contents = (release / "chunks.jsonl").read_bytes()
            findings = read_release(release, max_table_chars=40, table_tokenizer=tokenizer, max_table_tokens=2)["over_budget"]
            ids = {"file_id": "f", "page": 3}
            context = CheckContext(default_registry(), {}, release, {})
            signals = check_table_coverage(context, {"ids": ids, "table_chunks_over_budget": findings["f", 3],
                "table_findings": [{"page": 3, "rule": "survey", "reason": "unproven_ruled_panel"}]})
            self.assertEqual([s["code"] for s in signals], ["TABLE_CHUNK_OVER_BUDGET", "TABLE_RECONSTRUCTION_ABSTAINED"])
            self.assertEqual(signals[0]["evidence"]["chunks"][0]["tokens"], 3)
            self.assertEqual((release / "chunks.jsonl").read_bytes(), contents)
