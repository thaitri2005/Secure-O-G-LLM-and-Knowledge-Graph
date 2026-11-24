"""Cross-page activity rows retain both source fragments and one logical event."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pymupdf

from graph_builder.corpus.activity_detail import repair_document
from graph_builder.corpus.k1_build import logical_tables
from graph_builder.corpus.k1_validate import check_table_fragments
from graph_builder.corpus.qa.cell_evidence import CellEvidence


HEADER = ["Rpt. No.", "Date", "Time", "To", "Hrs", "End MD", "Ops Code", "Activity Description", "Non-Prod."]
FIRST = ["1", "01-Mar-19", "08:00", "10:30", "2.5", "1,702", "3-2-1", "Pressure held at -120.5 psi.", ""]
LAST = ["", "", "10:30", "12:00", "1.5", "1,704", "3-2-1", "Pulled the logging tool slowly", ""]
SUFFIX = "and checked its cable for damage."


def render(path, second_number):
    edges = [30, 74, 144, 190, 236, 277, 331, 389, 694, 759]
    with pymupdf.open() as pdf:
        for index, rows in enumerate(([HEADER, FIRST, LAST], [HEADER, ["", "", "", "", "", "", "", SUFFIX, ""]])):
            page = pdf.new_page(width=800, height=600)
            top = 490 if index == 0 else 48
            if index == 0:
                page.insert_text((34, top - 9), "Operations Activity Detail", fontsize=10)
            for r, row in enumerate(rows):
                y = top + 22 * r
                page.draw_line((edges[0], y), (edges[-1], y), width=.5)
                for c, value in enumerate(row):
                    if value:
                        page.insert_text((edges[c] + 3, y + 13), value, fontsize=8)
            bottom = top + 22 * len(rows)
            page.draw_line((edges[0], bottom), (edges[-1], bottom), width=.5)
            for x in edges:
                page.draw_line((x, top), (x, bottom), width=.5)
            page.insert_text((34, 584), f"Page: {second_number if index else 1} of 2   RIMBase 7.4.89.0", fontsize=8)
        pdf.save(path)


class ActivityDetailTests(unittest.TestCase):
    def test_activity_reconstruction_keeps_both_fragments_and_validates_the_joined_grid(self):
        seed = {"doc_id": "activity", "page": 1, "table_id": None, "section": None,
                "section_path": [], "ocr": False, "quality": "ok"}
        pages = [{"page": 1, "mode": "text"}, {"page": 2, "mode": "text"}]
        with TemporaryDirectory() as directory:
            proved, conflicting = (Path(directory) / f"{label}.pdf" for label in ("proved", "conflicting"))
            render(proved, 2)
            render(conflicting, 1)
            chunks, records, findings = repair_document(proved, pages, [seed], [], "activity", 1500, {})
            self.assertEqual(findings, [])
            table, = logical_tables(records, None, "f0000000000000000", "activity")
            self.assertEqual(table["grid"], [HEADER, FIRST, [*LAST[:7], LAST[7] + " " + SUFFIX, ""]])
            row_chunk, = [row for row in chunks if row.get("pages") == [1, 2]]
            self.assertEqual((row_chunk["row_start"], row_chunk["row_end"]), (2, 3))
            first, second = row_chunk["source_spans"]
            self.assertEqual((first["page"], first["end"]), (1, second["start"]))
            self.assertTrue(row_chunk["text"][second["start"]:].startswith(SUFFIX))
            errors = []
            check_table_fragments([table], errors)
            self.assertEqual(errors, [])
            with pymupdf.open(proved) as pdf:
                evidence = [row for part in table["parts"] for row in CellEvidence.fragment_rows(table, part, pdf[part["page"] - 1], None)]
            fragments = [row for row in evidence if (row["r"], row["c"]) == (2, 7)]
            self.assertEqual([(row["page"], row["text"], row["status"]) for row in fragments],
                             [(1, LAST[7], "source_supported"), (2, SUFFIX, "source_supported")])
            table["parts"][1]["cell_sources"][0]["text"] = "unrelated evidence"
            check_table_fragments([table], errors)
            self.assertEqual(len(errors), 1)

            chunks, records, findings = repair_document(conflicting, pages, [seed], [], "activity", 1500, {})
            self.assertEqual((chunks, records), ([seed], []))
            self.assertEqual(findings[0]["reason"], "unproven_activity_continuation")
