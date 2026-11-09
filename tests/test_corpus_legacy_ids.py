"""Old-to-new chunk id map: exact, near, duplicate and unmapped chunks, and the cited-chunk summary."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from graph_builder.corpus.legacy_ids import (cited_chunk_ids, jaccard, load_legacy_rows, map_legacy_chunks,
                                             summarize_legacy_map)

DOC = "gdr882_ak3_eowr"


def old(number: int, text: str, page: int = 1) -> dict:
    return {"doc_id": DOC, "chunk_id": f"{DOC}#c{number:04d}", "page": page, "text": text}


def new(label: str, text: str, page: int = 1) -> dict:
    return {"doc_id": DOC, "chunk_id": f"f0:s1:{label}", "page": page, "text": text, "type": "text"}


class MapLegacyChunksTests(unittest.TestCase):
    def test_exact_match_ignores_whitespace_and_keeps_pages(self):
        records = map_legacy_chunks([old(0, "Total  depth\nwas 1,955 ft", page=3)], [new("c0", "Total depth was 1,955 ft", page=4)])
        self.assertEqual(records, [{"old_chunk_id": f"{DOC}#c0000", "new_chunk_id": "f0:s1:c0", "method": "exact",
                                    "jaccard": 1.0, "old_page": 3, "new_page": 4}])

    def test_near_match_needs_the_threshold(self):
        text = " ".join(f"word{n}" for n in range(20))
        close = text + " extra"
        far = " ".join(f"word{n}" for n in range(12))
        [near] = map_legacy_chunks([old(0, text)], [new("c0", close)])
        self.assertEqual((near["method"], near["jaccard"]), ("near", round(20 / 21, 4)))
        [unmapped] = map_legacy_chunks([old(0, text)], [new("c0", far)])
        self.assertEqual((unmapped["method"], unmapped["new_chunk_id"], unmapped["jaccard"], unmapped["new_page"]),
                         ("unmapped", None, None, None))

    def test_duplicate_texts_use_each_new_chunk_once_in_old_id_order(self):
        records = map_legacy_chunks([old(1, "Same text."), old(0, "Same text."), old(2, "Same text.")],
                                    [new("c0", "Same text."), new("c1", "Same text.")])
        self.assertEqual([(r["old_chunk_id"][-6:], r["new_chunk_id"], r["method"]) for r in records],
                         [("#c0000", "f0:s1:c0", "exact"), ("#c0001", "f0:s1:c1", "exact"), ("#c0002", None, "unmapped")])

    def test_exact_matches_are_not_taken_by_near_matches(self):
        text = " ".join(f"word{n}" for n in range(20))
        records = map_legacy_chunks([old(0, text + " extra"), old(1, text)], [new("c0", text)])
        self.assertEqual([(r["method"], r["new_chunk_id"]) for r in records], [("unmapped", None), ("exact", "f0:s1:c0")])

    def test_best_near_match_goes_first(self):
        text = " ".join(f"word{n}" for n in range(30))
        one_off, two_off = text + " a", text + " a b"
        records = map_legacy_chunks([old(0, two_off), old(1, one_off)], [new("c0", text + " a b c")])
        self.assertEqual([(r["method"], r["new_chunk_id"]) for r in records], [("near", "f0:s1:c0"), ("unmapped", None)])

    def test_jaccard_of_empty_texts_is_zero(self):
        self.assertEqual(jaccard("", ""), 0.0)


class SummaryTests(unittest.TestCase):
    FACTS = {"document": DOC, "facts": [{"id": "g1", "chunks": ["c0000", "c0001"]}, {"id": "g2", "chunks": ["c0001", "c0002"]}]}

    def test_cited_chunks_are_full_sorted_unique_ids(self):
        self.assertEqual(cited_chunk_ids(self.FACTS), [f"{DOC}#c0000", f"{DOC}#c0001", f"{DOC}#c0002"])

    def test_summary_counts_methods_and_names_unmapped_cited_chunks(self):
        records = map_legacy_chunks([old(0, "alpha beta"), old(1, "gamma delta"), old(2, "epsilon"), old(3, "zeta")],
                                    [new("c0", "alpha beta"), new("c1", "gamma delta")])
        summary = summarize_legacy_map(records, self.FACTS)
        self.assertEqual((summary["old_chunks"], summary["exact"], summary["near"], summary["unmapped"]), (4, 2, 0, 2))
        self.assertEqual((summary["cited"], summary["cited_mapped"], summary["cited_unmapped"]), (3, 2, [f"{DOC}#c0002"]))

    def test_summary_without_facts_has_no_cited_counts(self):
        self.assertNotIn("cited", summarize_legacy_map([]))


class LoadTests(unittest.TestCase):
    def test_rows_of_other_documents_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chunks.jsonl"
            rows = [old(0, "kept"), {"doc_id": "other", "chunk_id": "other#c0000", "page": 1, "text": "dropped"}]
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="\n")
            self.assertEqual([row["text"] for row in load_legacy_rows(path)], ["kept"])


if __name__ == "__main__":
    unittest.main()
