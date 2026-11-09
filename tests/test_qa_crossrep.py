from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import unittest
from unittest import mock

from graph_builder.corpus.qa import crossrep as xr
from graph_builder.corpus.qa.signals import CheckContext, Registry

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / "data" / "interim" / "overnight" / "a403" / "test-tmp"  # git-ignored, inside the repository
REAL_RELEASES = [ROOT / "data/interim/k1-run/corpus/exports/ops-rebuild-r3-e2/releases/20261108T174020Z-e34a87c780d8",
                 ROOT / "data/interim/k1-run/corpus/exports/k1-legacy/releases/20261106T181142Z-67e8a9a1c73b"]
CONFIG = xr.load_config(ROOT / "configs/qa/cross_representation.json")
BAD = ("WARN", "ERROR")
SEVERITY = {code: severity for code, severity, _, _ in xr.REASONS}
EMPTY = xr.EMPTY_SHA256


def md(rows: list[list[str]]) -> str:
    return "\n".join("| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |" for row in rows)


GRID = [["Depth", "Type"], ["100", "A"], ["200", "B"], ["300", "C"], ["400", "D"]]


def table(grid=GRID, header_rows=1) -> dict:
    return {"table_id": "f1:t1", "file_id": "f1", "grid": copy.deepcopy(grid), "header_rows": header_rows, "num_rows": len(grid),
            "num_cols": len(grid[0]), "pages": [1]}


def chunk(index: int, start: int, end: int, grid=GRID, caption: str = "") -> dict:
    lines = ([caption] if caption else []) + [md([grid[0]]), "| " + " | ".join("---" for _ in grid[0]) + " |"] + [md([row]) for row in grid[start:end]]
    return {"chunk_id": f"f1:t1:c{index}", "child_index": index, "row_start": start, "row_end": end, "text": "\n".join(lines),
            "table_id": "f1:t1", "type": "table", "file_id": "f1", "parent_id": "f1:t1", "page": 1, "pages": [1], "regions": [{"page": 1, "bbox": [0, 0, 1, 1]}]}


def codes(found: list[tuple[str, dict]]) -> list[str]:
    return sorted({code for code, _ in found if SEVERITY[code] in BAD})


class ParsingTests(unittest.TestCase):
    def test_pipe_escape_and_blank_collapse(self) -> None:
        self.assertEqual(xr.split_cells("| a\\|b |  c   d |  |"), ["a|b", "c d", ""])

    def test_caption_header_and_rows_are_separated(self) -> None:
        parsed = xr.parse_table_chunk("Table 1: wells\n| A | B |\n| --- | --- |\n| 1 | 2 |")
        self.assertEqual((parsed["caption"], parsed["header"], parsed["separator_ok"], parsed["rows"]), (["Table 1: wells"], ["A", "B"], True, [["1", "2"]]))

    def test_text_without_table_is_reported(self) -> None:
        parsed = xr.parse_table_chunk("only prose")
        self.assertIsNone(parsed["header"])


class TableTests(unittest.TestCase):
    def test_single_and_split_chunks_with_repeated_header_and_caption_are_consistent(self) -> None:
        self.assertEqual(codes(xr.analyse_table(table(), [chunk(0, 1, 5)], CONFIG)), [])
        split = [chunk(0, 1, 3, caption="Table 1: depth"), chunk(1, 3, 5, caption="Table 1: depth")]
        self.assertEqual(codes(xr.analyse_table(table(), split, CONFIG)), [])

    def test_rendered_header_may_differ_from_header_rows(self) -> None:
        grid = [["Depth", "Type"], ["Depth", "Kind"], ["100", "A"]]
        record = table(grid, header_rows=2)  # the chunker rendered one header row; row 1 is a body row
        self.assertEqual(codes(xr.analyse_table(record, [chunk(0, 1, 3, grid=grid)], CONFIG)), [])

    def test_merged_header_rows_with_any_separator_are_consistent(self) -> None:
        grid = [["Depth", "Depth", "Type"], ["From", "To", ""], ["1", "2", "A"]]
        record = table(grid, header_rows=2)
        merged = chunk(0, 2, 3, grid=grid)
        merged["text"] = "| Depth - From | Depth - To | Type |\n| --- | --- | --- |\n| 1 | 2 | A |"
        self.assertEqual(codes(xr.analyse_table(record, [merged], CONFIG)), [])

    def test_cell_changed_only_in_grid_or_only_in_chunk_is_flagged(self) -> None:
        changed = table()
        changed["grid"][2][0] = "201"
        self.assertEqual(codes(xr.analyse_table(changed, [chunk(0, 1, 5)], CONFIG)), ["XREP_TABLE_CHUNK_MISMATCH"])
        other = chunk(0, 1, 5)
        other["text"] = other["text"].replace("| 300 | C |", "| 301 | C |")
        self.assertEqual(codes(xr.analyse_table(table(), [other], CONFIG)), ["XREP_TABLE_CHUNK_MISMATCH"])

    def test_swapped_rows_in_one_representation_are_flagged(self) -> None:
        changed = table()
        changed["grid"][1], changed["grid"][2] = changed["grid"][2], changed["grid"][1]
        found = xr.analyse_table(changed, [chunk(0, 1, 5)], CONFIG)
        self.assertEqual(codes(found), ["XREP_TABLE_CHUNK_MISMATCH"])
        self.assertEqual(found[0][1]["mismatches"][0]["first"][0]["kind"], "cell_text")

    def test_documented_blind_spot_consistent_change_in_both_representations(self) -> None:
        changed = table()
        changed["grid"][2][0] = "201"
        other = chunk(0, 1, 5, grid=changed["grid"])
        self.assertEqual(codes(xr.analyse_table(changed, [other], CONFIG)), [])  # NOT detectable by design

    def test_row_end_beyond_row_count_is_an_error(self) -> None:
        bad = chunk(0, 1, 5)
        bad["row_end"] = 9
        found = xr.analyse_table(table(), [bad], CONFIG)
        self.assertIn("XREP_ROW_RANGE_INVALID", codes(found))
        self.assertEqual(SEVERITY["XREP_ROW_RANGE_INVALID"], "ERROR")

    def test_gap_between_chunk_ranges_is_flagged(self) -> None:
        self.assertIn("XREP_ROW_RANGE_COVERAGE", codes(xr.analyse_table(table(), [chunk(0, 1, 2), chunk(1, 3, 5)], CONFIG)))
        self.assertIn("XREP_ROW_RANGE_COVERAGE", codes(xr.analyse_table(table(), [chunk(0, 1, 4)], CONFIG)))  # stops before the last row

    def test_table_without_chunk_and_deleted_continuation_are_flagged(self) -> None:
        self.assertEqual(codes(xr.analyse_table(table(), [], CONFIG)), ["XREP_TABLE_NO_CHUNK"])
        self.assertIn("XREP_ROW_RANGE_COVERAGE", codes(xr.analyse_table(table(), [chunk(0, 1, 3)], CONFIG)))

    def test_header_changed_in_one_chunk_and_caption_drift_are_flagged(self) -> None:
        split = [chunk(0, 1, 3), chunk(1, 3, 5)]
        split[1]["text"] = split[1]["text"].replace("| Depth | Type |", "| Depth | Kind |")
        self.assertEqual(codes(xr.analyse_table(table(), split, CONFIG)), ["XREP_TABLE_CHUNK_MISMATCH"])
        drift = [chunk(0, 1, 3, caption="Table 1"), chunk(1, 3, 5, caption="Table 2")]
        self.assertEqual(codes(xr.analyse_table(table(), drift, CONFIG)), ["XREP_TABLE_CHUNK_MISMATCH"])

    def test_chunk_without_markdown_and_wrong_grid_shape_are_flagged(self) -> None:
        prose = chunk(0, 1, 5)
        prose["text"] = "prose only"
        self.assertEqual(codes(xr.analyse_table(table(), [prose], CONFIG)), ["XREP_TABLE_CHUNK_MISMATCH"])
        short = table()
        short["num_rows"] = 9
        self.assertIn("XREP_TABLE_SHAPE", codes(xr.analyse_table(short, [chunk(0, 1, 5)], CONFIG)))

    def test_pipe_inside_a_cell_survives_the_round_trip(self) -> None:
        grid = [["A", "B"], ["x|y", "2"]]
        self.assertEqual(codes(xr.analyse_table(table(grid), [chunk(0, 1, 2, grid=grid)], CONFIG)), [])


FORM = {"form_id": "f1:f1", "file_id": "f1", "page": 1, "fields": [{"key": "Well ID:", "value": "AK-3"}, {"key": "Depth", "value": "1700"}, {"key": "Note:", "value": ""}]}


def form_chunk(text: str) -> dict:
    return {"chunk_id": "f1:f1:c0", "child_index": 0, "text": text, "form_id": "f1:f1", "type": "form", "file_id": "f1", "parent_id": "f1:f1"}


class FormTests(unittest.TestCase):
    TEXT = "Well ID: AK-3\nDepth: 1700\nNote: "

    def test_matching_form_is_consistent_including_empty_value(self) -> None:
        self.assertEqual(codes(xr.analyse_form(FORM, [form_chunk(self.TEXT)], CONFIG)), [])

    def test_value_changed_in_either_representation_is_flagged(self) -> None:
        self.assertEqual(codes(xr.analyse_form(FORM, [form_chunk(self.TEXT.replace("1700", "1701"))], CONFIG)), ["XREP_FORM_CHUNK_MISMATCH"])
        changed = copy.deepcopy(FORM)
        changed["fields"][1]["value"] = "1800"
        self.assertEqual(codes(xr.analyse_form(changed, [form_chunk(self.TEXT)], CONFIG)), ["XREP_FORM_CHUNK_MISMATCH"])

    def test_missing_chunk_is_an_error_and_wrong_pairing_in_both_is_not_seen(self) -> None:
        self.assertEqual(codes(xr.analyse_form(FORM, [], CONFIG)), ["XREP_FORM_NO_CHUNK"])
        swapped = copy.deepcopy(FORM)
        swapped["fields"][0]["value"], swapped["fields"][1]["value"] = "1700", "AK-3"
        both = form_chunk("Well ID: 1700\nDepth: AK-3\nNote: ")
        self.assertEqual(codes(xr.analyse_form(swapped, [both], CONFIG)), [])  # documented blind spot


class PageTests(unittest.TestCase):
    def test_page_numbers(self) -> None:
        self.assertTrue(xr.page_numbers_ok({"page_count": 2}, [{"page": 1}, {"page": 2}])[0])
        self.assertFalse(xr.page_numbers_ok({"page_count": 3}, [{"page": 1}, {"page": 2}])[0])
        self.assertFalse(xr.page_numbers_ok({"page_count": 2}, [{"page": 1}, {"page": 3}])[0])

    def test_chunk_page_problems(self) -> None:
        good = {"page": 2, "pages": [2], "regions": [{"page": 2}]}
        self.assertEqual(xr.chunk_page_problems(good, {"pages": [1, 2]}, None, "text"), [])
        self.assertIn("page not in pages", xr.chunk_page_problems({**good, "page": 5}, None, None, "text"))
        self.assertIn("region page not in pages", xr.chunk_page_problems({**good, "regions": [{"page": 3}]}, None, None, "text"))
        self.assertIn("pages not inside parent pages", xr.chunk_page_problems(good, {"pages": [1]}, None, "text"))
        self.assertIn("page differs from form page", xr.chunk_page_problems(good, None, {"page": 1}, "form"))


def write_jsonl(path: Path, items: list[dict]) -> None:
    path.write_bytes(("\n".join(json.dumps(i, sort_keys=True) for i in items) + ("\n" if items else "")).encode("utf-8"))


def mini_release(target: Path, extra_page: bool = False) -> Path:
    """A tiny K1-shaped release (only the groups the cross-representation checks read)."""
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    pages = [{"file_id": "f1", "page": 1, "page_id": "f1:p1", "filtered_text_sha256": "x", "status": "ok"},
             {"file_id": "f1", "page": 2, "page_id": "f1:p2", "filtered_text_sha256": "x", "status": "ok"}]
    if extra_page:
        pages.append({"file_id": "f1", "page": 3, "page_id": "f1:p3", "filtered_text_sha256": EMPTY, "status": "ok"})
    text_chunk = {"chunk_id": "f1:s1:c0", "child_index": 0, "file_id": "f1", "parent_id": "f1:s1", "page": 2, "pages": [2], "regions": [], "text": "hello", "type": "text",
                  "table_id": None, "form_id": None}
    write_jsonl(target / "files.jsonl", [{"file_id": "f1", "doc_id": "d1", "page_count": len(pages)}])
    write_jsonl(target / "pages.jsonl", pages)
    write_jsonl(target / "tables.jsonl", [table()])
    write_jsonl(target / "forms.jsonl", [FORM])
    write_jsonl(target / "parents.jsonl", [{"parent_id": "f1:s1", "file_id": "f1", "type": "text", "pages": [2]},
                                           {"parent_id": "f1:t1", "file_id": "f1", "type": "table", "pages": [1]},
                                           {"parent_id": "f1:f1", "file_id": "f1", "type": "form", "pages": [1]}])
    write_jsonl(target / "chunks.jsonl", [text_chunk, chunk(0, 1, 5), {**form_chunk(FormTests.TEXT), "page": 1, "pages": [1], "regions": []}])
    (target / "manifest.json").write_text(json.dumps({"pages_without_context": []}), encoding="utf-8")
    return target


class ReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.release = mini_release(SCRATCH / "mini")

    def tearDown(self) -> None:
        shutil.rmtree(SCRATCH, ignore_errors=True)

    def bad_codes(self, findings: xr.Findings) -> list[str]:
        return sorted(code for code in findings.all_codes() if SEVERITY.get(code, "ERROR") in BAD)

    def test_clean_mini_release_has_no_warning(self) -> None:
        findings = xr.analyse_release(self.release, CONFIG)
        self.assertEqual(self.bad_codes(findings), [])
        self.assertEqual((findings.stats["tables"], findings.stats["forms"], findings.stats["pages"]), (1, 1, 2))

    def test_page_count_orphans_and_uncovered_page_are_flagged(self) -> None:
        write_jsonl(self.release / "files.jsonl", [{"file_id": "f1", "doc_id": "d1", "page_count": 5}])
        chunks = [json.loads(line) for line in (self.release / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
        chunks[1]["table_id"] = "f1:t9"
        chunks[0]["pages"], chunks[0]["page"] = [1], 1
        write_jsonl(self.release / "chunks.jsonl", chunks)
        found = xr.analyse_release(self.release, CONFIG)
        self.assertEqual(self.bad_codes(found), ["XREP_CHUNK_PAGE_INCONSISTENT", "XREP_PAGE_COUNT_MISMATCH", "XREP_PAGE_WITHOUT_CHUNKS", "XREP_TABLE_CHUNK_ORPHAN", "XREP_TABLE_NO_CHUNK"])

    def test_empty_page_digest_is_info_and_manifest_exception_is_respected(self) -> None:
        release = mini_release(SCRATCH / "mini3", extra_page=True)
        found = xr.analyse_release(release, CONFIG)
        self.assertEqual(self.bad_codes(found), [])
        self.assertEqual(found.all_codes()["XREP_PAGE_EMPTY_BY_DIGEST"], 1)
        pages = [json.loads(line) for line in (release / "pages.jsonl").read_text(encoding="utf-8").splitlines()]
        pages[2]["filtered_text_sha256"] = "y"
        write_jsonl(release / "pages.jsonl", pages)
        self.assertEqual(self.bad_codes(xr.analyse_release(release, CONFIG)), ["XREP_PAGE_WITHOUT_CHUNKS"])
        (release / "manifest.json").write_text(json.dumps({"pages_without_context": [{"doc_id": "d1", "page": 3}]}), encoding="utf-8")
        self.assertEqual(self.bad_codes(xr.analyse_release(release, CONFIG)), [])

    def test_parent_without_chunks_and_inconsistent_chunk_page(self) -> None:
        parents = [json.loads(line) for line in (self.release / "parents.jsonl").read_text(encoding="utf-8").splitlines()]
        write_jsonl(self.release / "parents.jsonl", parents + [{"parent_id": "f1:s9", "file_id": "f1", "type": "text", "pages": [1]}])
        chunks = [json.loads(line) for line in (self.release / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
        chunks[0]["pages"] = [1]
        write_jsonl(self.release / "chunks.jsonl", chunks)
        self.assertEqual(self.bad_codes(xr.analyse_release(self.release, CONFIG)), ["XREP_CHUNK_PAGE_INCONSISTENT", "XREP_PAGE_WITHOUT_CHUNKS", "XREP_PARENT_WITHOUT_CHUNKS"])

    def test_one_failing_table_becomes_qa_error_and_others_continue(self) -> None:
        with mock.patch.object(xr, "analyse_table", side_effect=RuntimeError("boom")):
            found = xr.analyse_release(self.release, CONFIG)
        self.assertEqual(found.all_codes()["QA_ERROR"], 1)
        self.assertEqual(found.stats["forms"], 1)

    def test_registry_grants_level_only_to_a_consistent_table(self) -> None:
        def level(release: Path) -> tuple[str | None, list[str]]:
            registry = xr.register_crossrep(Registry())
            context = CheckContext(registry, {}, release, {})
            signals, ran, granted = registry.run("table", context, {"ids": {"file_id": "f1", "table_id": "f1:t1"}}, {"table_id": "f1:t1"})
            return granted, [s["code"] for s in signals]
        self.assertEqual(level(self.release), ("CROSS_REPRESENTATION_CONSISTENT", []))
        chunks = [json.loads(line) for line in (self.release / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
        chunks[1]["text"] = chunks[1]["text"].replace("| 300 | C |", "| 301 | C |")
        write_jsonl(self.release / "chunks.jsonl", chunks)
        self.assertEqual(level(self.release), (None, ["XREP_TABLE_CHUNK_MISMATCH"]))

    def test_standalone_output_is_deterministic_and_never_claims_content_verification(self) -> None:
        first, second = xr.run_standalone(self.release, SCRATCH / "out"), xr.run_standalone(self.release)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        written = (SCRATCH / "out" / "qa-crossrep.json").read_text(encoding="utf-8").lower()
        self.assertNotIn("content verified", written)
        self.assertEqual(first["completeness"], "UNKNOWN")


@unittest.skipUnless(all(path.is_dir() for path in REAL_RELEASES), "real K1 releases are not available")
class RealReleaseTests(unittest.TestCase):
    def test_no_warning_or_error_signal_on_both_real_releases(self) -> None:
        for release in REAL_RELEASES:
            findings = xr.analyse_release(release, CONFIG)
            bad = {code: n for code, n in findings.all_codes().items() if SEVERITY[code] in BAD}
            self.assertEqual(bad, {}, release.name)
            self.assertEqual(findings.stats["forms"], 81)
            self.assertEqual(findings.stats["form_chunks"], 81)
            self.assertGreaterEqual(findings.stats["tables"], 191)


if __name__ == "__main__":
    unittest.main()
