"""A tiny synthetic K1 package read through the graphrag loaders and the compatibility check script."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graphrag.data import chunks_on_pages, daily_rows, load_chunks  # noqa: E402
from graphrag.ontology import table_rows  # noqa: E402

SPEC = importlib.util.spec_from_file_location("check_k1_graphrag_compat", ROOT / "scripts/check_k1_graphrag_compat.py")
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)

REPORT = "sample-appx-30-6-dailyreportsummaryrpt-0a1b2c3d"
FILE = "f" + "1" * 16


def chunk(chunk_id: str, doc_id: str, page: int, kind: str = "text", text: str = "Passage.", table_id: str | None = None,
          row_start: int | None = None, row_end: int | None = None) -> dict:
    return {"chunk_id": chunk_id, "doc_id": doc_id, "page": page, "pages": [page], "type": kind, "section": None,
            "text": text, "table_id": table_id, "row_start": row_start, "row_end": row_end, "context": {}}


ROWS = [chunk(f"{FILE}:s1:c0", REPORT, 17, text="Report For 28-Aug-16"),
        chunk(f"{FILE}:t1:c0", REPORT, 17, "table", "Depth | 465", f"{FILE}:t1", 0, 2),
        chunk("f" + "2" * 16 + ":s1:c0", "gdr882_ak3_eowr", 1, text="End of well report")]
TABLE = {"table_id": f"{FILE}:t1", "doc_id": REPORT, "logical_id": f"{REPORT}#t0001",
         "cells": [{"r": 0, "c": 0, "text": " Depth "}, {"r": 0, "c": 1, "text": "465"},
                   {"r": 1, "c": 1, "text": "ft"}, {"r": 1, "c": 0, "text": "Unit"}]}


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="\n")


class SyntheticPackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        write_jsonl(self.directory / "chunks.jsonl", ROWS)
        write_jsonl(self.directory / "tables.jsonl", [TABLE])

    def test_load_chunks_reads_every_k1_row(self):
        chunks = load_chunks(path=self.directory / "chunks.jsonl")
        self.assertEqual([c.id for c in chunks], [row["chunk_id"] for row in ROWS])
        self.assertEqual((chunks[1].kind, chunks[1].table_id, chunks[1].row_start, chunks[1].row_end), ("table", f"{FILE}:t1", 0, 2))
        self.assertEqual(len(load_chunks(["gdr882_ak3_eowr"], self.directory / "chunks.jsonl")), 1)

    def test_table_rows_orders_cells_and_strips_text(self):
        self.assertEqual(table_rows(TABLE), [["Depth", "465"], ["Unit", "ft"]])

    def test_daily_report_rules_find_the_attachment_and_its_number(self):
        rows = daily_rows(self.directory / "chunks.jsonl")
        self.assertEqual({row["doc_id"] for row in rows}, {REPORT})
        self.assertEqual(REPORT.split("-appx-")[1][:2], "30")
        self.assertEqual(chunks_on_pages([{"appx": "30", "page": 17}], rows), [ROWS[0]["chunk_id"], ROWS[1]["chunk_id"]])

    def run_check(self, function, *arguments):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            result = function(*arguments)
        return result, output.getvalue()

    def test_script_checks_pass_on_the_synthetic_package(self):
        chunks, loaded = self.run_check(CHECK.check_load, self.directory / "chunks.jsonl")[0]
        self.assertTrue(loaded)
        self.assertEqual(len(chunks), 3)
        self.assertTrue(self.run_check(CHECK.check_tables, self.directory / "chunks.jsonl")[0])

    def test_table_check_fails_for_a_table_chunk_without_its_table(self):
        write_jsonl(self.directory / "tables.jsonl", [dict(TABLE, table_id="other")])
        result, output = self.run_check(CHECK.check_tables, self.directory / "chunks.jsonl")
        self.assertFalse(result)
        self.assertIn("table chunks without a table: 1", output)

    def test_daily_report_check_needs_all_four_attachments(self):
        self.assertFalse(self.run_check(CHECK.check_daily_reports, self.directory / "chunks.jsonl")[0])

    def test_hit_rates_count_ranks_up_to_each_cutoff(self):
        self.assertEqual(CHECK.rates([1, 4, None, 12]), {"hit@1": 0.25, "hit@3": 0.25, "hit@5": 0.5, "hit@10": 0.5})

    def test_graphrag_has_no_id_format_gaps_left(self):
        # The four gaps E30 listed were fixed in graphrag (Track B log B-C28).
        output = self.run_check(CHECK.report_id_format_gaps, ROWS[0]["chunk_id"])[1]
        for name in ("graphrag/citations.py", "graphrag/baseline.py", "graphrag/validate.py"):
            self.assertNotIn(name, output)
        self.assertIn("none:", output)


if __name__ == "__main__":
    unittest.main()
