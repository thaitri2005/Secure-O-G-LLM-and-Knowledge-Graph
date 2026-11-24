"""FR-25: the optional table joiner decides per page pair from geometry and header repetition, never forces a join, loses no data and
leaves K1 untouched when the option is absent."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

try:
    import fitz  # PyMuPDF draws the synthetic PDFs for the tests marked below.
except ImportError:
    fitz = None

from graph_builder.corpus.k1_build import map_children, table_owners
from graph_builder.corpus.k1_config import load_k1_config, validate_k1_config
from graph_builder.corpus.quarantine import chunk_sidecar
from graph_builder.corpus.table_join import (apply_groups, assess_pair, candidate_pairs, header_like, join_tables, leading_header_rows, number_of,
                                             plan_joins, sample_pages, series_check, text_lines, validate_table_join)

ROOT = Path(__file__).resolve().parents[1]
OPTIONS = validate_table_join(json.loads((ROOT / "configs/corpus/table_join.json").read_text(encoding="utf-8")))
FID = "f" + "0" * 16
WIDTH, HEIGHT = 600.0, 800.0
HEADER = ["Item", "Plan", "Actual"]


def words_for(rows: list[list[str]], top: float, left: float = 50.0, step: float = 14.0, column: float = 150.0) -> list[dict]:
    """Words of a table printed line by line: one text row per grid row, one word per cell (cells with several words are split)."""
    words = []
    for index, row in enumerate(rows):
        y = top + index * step
        for c, cell in enumerate(row):
            x = left + c * column
            for piece in cell.split():
                words.append({"text": piece, "bbox": [x, y, x + 6 * len(piece), y + 10], "row": index})
                x += 6 * len(piece) + 4
    return words


def layer(words: list[dict], rotation: int = 0, width: float = WIDTH, height: float = HEIGHT) -> dict:
    return {"words": [dict(w, row=(w["row"], round(w["bbox"][1]))) for w in words], "width": width, "height": height, "rotation": rotation}


def table(number: int, page: int, grid: list[list[str]], header_rows: int, top: float, source: str = "#/tables/", regions: list | None = None,
          cols: int | None = None) -> dict:
    """A K1 table record as ``logical_tables`` produces it."""
    num_cols = cols or len(grid[0])
    bbox = [50.0, top, 50.0 + 150.0 * num_cols, top + 14.0 * len(grid) + 4]
    cells = [{"r": r, "c": c, "row_span": 1, "col_span": 1, "text": value, "is_header": r < header_rows} for r, row in enumerate(grid) for c, value in enumerate(row)]
    labels = [" / ".join(dict.fromkeys(row[c] for row in grid[:header_rows] if row[c])) for c in range(num_cols)]
    return dict(table_id=f"{FID}:t{number}", logical_id=f"doc#t{number:04d}", file_id=FID, doc_id="doc", pages=[page], grid=grid, header_rows=header_rows,
                num_rows=len(grid), num_cols=num_cols, cells=cells,
                parts=[dict(source_ref=f"{source}{number}", page=page, bbox=bbox, row_start=0, row_end=len(grid), header=grid[:header_rows])],
                join={"status": "single", "reasons": []},
                rows_text=["; ".join(f"{labels[c]}: {v}" if labels[c] else v for c, v in enumerate(row)) for row in grid[header_rows:]],
                regions=regions or [{"page": page, "bbox": bbox}])


def body(start: int, count: int) -> list[list[str]]:
    return [[f"Row{start + i}", str(100 + 10 * (start + i)), str(200 + 10 * (start + i))] for i in range(count)]


def pair(grid_a=None, grid_b=None, header_a=1, header_b=1, top_a=600.0, top_b=70.0, words_a=None, words_b=None, extra_b=None, **kw):
    """Two tables on pages 1 and 2 with matching printed text, plus their layers. Page 1 ends at the bottom, page 2 starts at the top."""
    grid_a = grid_a or [HEADER] + body(1, 8)
    grid_b = grid_b or [HEADER] + body(9, 5)
    a, b = table(1, 1, grid_a, header_a, top_a), table(2, 2, grid_b, header_b, top_b)
    layers = {1: layer(words_a if words_a is not None else words_for(grid_a, top_a)),
              2: layer((words_b if words_b is not None else words_for(grid_b, top_b)) + (extra_b or []))}
    return a, b, layers


def plan(tables, layers, pages=2, options=OPTIONS):
    return plan_joins(tables, lambda n: layers[n], pages, options)


class DecisionTests(unittest.TestCase):
    def decide(self, a, b, layers, options=OPTIONS):
        result = plan([a, b], layers, options=options)
        self.assertEqual(len(result["decisions"]), 1)
        return result["decisions"][0], result

    def test_repeated_header_is_joined_and_the_header_row_is_dropped(self):
        a, b, layers = pair()
        decision, result = self.decide(a, b, layers)
        self.assertEqual(decision["decision"], "joined", decision["reasons"])
        self.assertIn("header_repeated", decision["reasons"])
        self.assertEqual(decision["dropped_header_rows"], 1)
        self.assertEqual([[t["table_id"] for t in g] for g in result["groups"]], [[a["table_id"], b["table_id"]]])

    def test_source_proof_requires_more_than_the_same_header(self):
        options = copy.deepcopy(OPTIONS)
        options["continuity"]["require_source_proof"] = True
        a, b, layers = pair()
        decision, _ = self.decide(a, b, layers, options)
        self.assertEqual(decision["decision"], "uncertain")
        layers[1]["words"] += layer(words_for([["Pressure measurements"]], 582))["words"]
        layers[2]["words"] += layer(words_for([["Pressure measurements (continued)"]], 52))["words"]
        decision, result = self.decide(a, b, layers, options)
        self.assertEqual(decision["reasons"], ["printed_continuation"])
        joined, _, failures = apply_groups([a, b], result, options)
        self.assertEqual(failures, [])
        self.assertEqual(joined[0]["grid"], a["grid"] + b["grid"][1:])
        self.assertEqual(joined[0]["parts"][1]["page"], 2)

    def test_headerless_regular_series_can_continue_within_a_proven_report(self):
        options = copy.deepcopy(OPTIONS)
        options["continuity"]["require_source_proof"] = True
        left = [["Depth", "Plan", "Actual"], *[[str(i), "23", "25"] for i in range(10, 18)]]
        for start, expected in ((18, "joined"), (22, "uncertain")):
            right = [[str(i), "23", "25"] for i in range(start, start + 4)]
            a, b, layers = pair(grid_a=left, grid_b=right, header_b=1)
            context = {"well": "A-01", "report_date": "2025-01-04"}
            result = plan_joins([a, b], layers.__getitem__, 2, options, report_contexts={1: context, 2: context})
            decision, = result["decisions"]
            self.assertEqual(decision["decision"], expected)
            if expected == "joined":
                tables, _, failures = apply_groups([a, b], result, options)
                self.assertEqual(failures, [])
                self.assertEqual(tables[0]["grid"], left + right)
                self.assertEqual(tables[0]["parts"][1]["rendered_body_header_rows"], 1)

    def test_continuation_cannot_cross_a_known_report_date_or_well_change(self):
        a, b, layers = pair()
        context = {"report_date": "2025-01-02", "well": "A-01"}
        for key, value in (("report_date", "2025-01-03"), ("well", "B-02")):
            with self.subTest(key=key):
                outcome = plan_joins([a, b], layers.__getitem__, 2, OPTIONS,
                                     report_contexts={1: context, 2: {**context, key: value}})
                self.assertEqual(outcome["groups"], [])
                self.assertEqual(outcome["decisions"][0]["reasons"], ["report_context_differs"])
                self.assertEqual(outcome["decisions"][0]["evidence"]["different_fields"], [key])
        for second in (context, {"well": "a-01"}, {}):
            outcome = plan_joins([a, b], layers.__getitem__, 2, OPTIONS, report_contexts={1: context, 2: second})
            self.assertEqual(len(outcome["groups"]), 1)

    @unittest.skipIf(fitz is None, "PyMuPDF not available")
    def test_visually_matching_candidates_keep_distinct_source_report_ids_separate(self):
        from graph_builder.corpus.report_fields import source_report_identity
        from graph_builder.corpus.text_layer import source_page

        a, b, layers = pair()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reports.pdf"
            with fitz.open() as pdf:
                for report in ("034 23/09/2018", "34 2018-09-23", "035 24/09/2018", "34 02/03/2018", "34 2018-02-03"):
                    page = pdf.new_page(width=600, height=800)
                    page.insert_text((50, 40), "DAILY DRILLING REPORT")
                    page.insert_text((50, 60), "WELL: Oil Basin 5")
                    page.insert_text((50, 80), f"REPORT # {report}")
                pdf.save(path)
            first, same, next_report, ambiguous, equivalent = [
                source_report_identity(source_page(path, page, displayed_origin=True)) for page in (1, 2, 3, 4, 5)]
        self.assertEqual(first, {"report_number": ("34",), "report_reference_date": ("2018-09-23",),
                                 "well": ("oil basin 5",)})
        self.assertEqual(first, same)
        layers[1]["identity"], layers[2]["identity"] = first, next_report
        result = plan_joins([a, b], layers.__getitem__, 2, OPTIONS, source_identity=lambda layer: layer["identity"])
        self.assertEqual(result["groups"], [])
        self.assertEqual(result["decisions"][0]["reasons"], ["source_report_identity_differs"])
        layers[2]["identity"] = same
        result = plan_joins([a, b], layers.__getitem__, 2, OPTIONS, source_identity=lambda layer: layer["identity"])
        self.assertEqual(len(result["groups"]), 1)
        layers[1]["identity"], layers[2]["identity"] = ambiguous, equivalent
        result = plan_joins([a, b], layers.__getitem__, 2, OPTIONS, source_identity=lambda layer: layer["identity"])
        self.assertEqual(len(result["groups"]), 1)

    def test_repeated_body_text_is_kept_when_the_header_repeats(self):
        grid = [HEADER] + [["Drill", "Pump", "Circulate"] for _ in range(8)]
        a, b, layers = pair(grid_a=grid, grid_b=grid)
        decision, result = self.decide(a, b, layers)
        self.assertEqual((decision["decision"], decision["dropped_header_rows"]), ("joined", 1))
        tables, _, _ = apply_groups([a, b], result, OPTIONS)
        self.assertEqual(tables[0]["grid"], grid + grid[1:])

    def test_headerless_continuation_needs_same_report_and_continuing_depth(self):
        from graph_builder.corpus.qa.table_headers import add_continuation_headers

        header = ["Item", "Measured Depth (ft)", "Pressure"]
        a, b, layers = pair(grid_a=[header] + body(1, 8), grid_b=body(9, 5), header_b=0)
        context = {"report_date": "2026-11-23", "well": "Test Well 5"}
        decision = plan_joins([a, b], layers.__getitem__, 2, OPTIONS, report_contexts={1: context, 2: context})
        self.assertEqual(decision["decisions"][0]["reasons"], ["headerless_monotonic_series_within_report"])
        row = {"table_id": a["table_id"], "page": 2, "pages": [2], "type": "table", "text": "printed table body"}
        enriched, = add_continuation_headers([row], {(a["table_id"], 2): (1, header, 9, 0)})
        self.assertEqual(enriched["table_header_page"], 1)
        self.assertTrue(enriched["text"].endswith("\n" + row["text"]))
        self.assertIn("Measured Depth", enriched["text"])
        for other in ({}, dict(context, report_date="2026-11-24")):
            result = plan_joins([a, b], layers.__getitem__, 2, OPTIONS, report_contexts={1: context, 2: other})
            self.assertFalse(result["groups"])

    def test_orphaned_header_alone_at_the_page_bottom_is_joined(self):
        a, b, layers = pair(grid_a=[HEADER], grid_b=body(1, 5), header_a=1, header_b=0, top_a=700.0)
        decision, _ = self.decide(a, b, layers)
        self.assertEqual(decision["decision"], "joined", decision["reasons"])
        self.assertIn("orphan_header", decision["reasons"])
        self.assertEqual(decision["dropped_header_rows"], 0)

    def test_numeric_looking_single_row_is_not_an_orphaned_header(self):
        a, b, layers = pair(grid_a=[["Depth", "100", "200"]], grid_b=body(1, 5), header_a=1, header_b=0, top_a=700.0)
        decision, _ = self.decide(a, b, layers)
        self.assertEqual(decision["decision"], "uncertain")
        self.assertIn("no_continuation_signal", decision["reasons"])

    def test_same_structure_without_a_continuation_signal_is_uncertain_not_joined(self):
        a, b, layers = pair(grid_a=body(1, 8), grid_b=body(9, 5), header_a=0, header_b=0)
        decision, result = self.decide(a, b, layers)
        self.assertEqual(decision["decision"], "uncertain")
        self.assertEqual(result["groups"], [])
        self.assertIn("structure_matches", decision["reasons"])

    def test_grid_header_that_the_pdf_does_not_repeat_is_not_a_signal(self):
        grid_a, grid_b = [HEADER] + body(1, 8), [HEADER] + body(9, 5)
        other = [["Different", "Words", "Here"]] + body(9, 5)  # what page 2 really prints
        a, b, layers = pair(grid_a, grid_b, words_b=words_for(other, 70.0))
        decision, _ = self.decide(a, b, layers)
        self.assertEqual(decision["decision"], "uncertain")

    def test_pdf_repeats_a_header_the_grid_cannot_drop_is_uncertain(self):
        grid_a, grid_b = [HEADER] + body(1, 8), body(9, 5)  # the grid of b lost its header row but the page prints it
        a, b, layers = pair(grid_a, grid_b, header_b=0, words_b=words_for([HEADER] + body(9, 5), 70.0))
        decision, _ = self.decide(a, b, layers)
        self.assertEqual(decision["decision"], "uncertain")
        self.assertIn("header_repeated_on_pdf_not_in_grid", decision["reasons"])

    def test_title_above_the_second_table_means_it_does_not_start_the_page(self):
        a, b, layers = pair(extra_b=[{"text": "New", "bbox": [50, 66, 80, 76], "row": 99}, {"text": "table", "bbox": [84, 66, 120, 76], "row": 99}], top_b=90.0)
        decision, _ = self.decide(a, b, layers)
        self.assertEqual(decision["decision"], "separate")
        self.assertIn("b_not_at_page_start", decision["reasons"])

    def test_text_below_the_first_table_means_it_does_not_end_the_page(self):
        a, b, layers = pair(top_a=500.0)
        decision, _ = self.decide(a, b, layers)
        self.assertEqual(decision["decision"], "separate")
        self.assertIn("a_not_at_page_end", decision["reasons"])

    def test_other_column_count_stays_separate(self):
        a, b, layers = pair(grid_b=[HEADER + ["Extra"]] + [row + ["x"] for row in body(9, 5)])
        decision, _ = self.decide(a, b, layers)
        self.assertEqual(decision["decision"], "separate")
        self.assertIn("column_count_differs", decision["reasons"])

    def test_shifted_table_extent_stays_separate(self):
        a, b, layers = pair()
        left, top, right, bottom = b["regions"][0]["bbox"]
        b["regions"] = [{"page": 2, "bbox": [left + 90, top, right + 90, bottom]}]
        layers[2] = layer(words_for(b["grid"], 70.0, left=140.0))
        decision, _ = self.decide(a, b, layers)
        self.assertEqual(decision["decision"], "separate")
        self.assertIn("x_extent_differs", decision["reasons"])

    def test_rotation_page_size_and_source_limits(self):
        a, b, layers = pair()
        layers[2]["rotation"] = 90
        self.assertIn("rotation_unsupported", self.decide(a, b, layers)[0]["reasons"])
        layers[1]["rotation"], layers[2]["rotation"] = 270, 0
        self.assertIn("rotation_differs", self.decide(a, b, layers)[0]["reasons"])
        a, b, layers = pair()
        layers[2]["width"] = 700.0
        self.assertIn("page_size_differs", self.decide(a, b, layers)[0]["reasons"])
        a, b, layers = pair()
        a["parts"][0]["source_ref"] = "textlayer:operations_summary:p1:0"
        self.assertIn("source_not_supported", self.decide(a, b, layers)[0]["reasons"])

    def test_rotated_270_pages_with_the_same_structure_are_supported(self):
        a, b, layers = pair()
        layers[1]["rotation"] = layers[2]["rotation"] = 270
        self.assertEqual(self.decide(a, b, layers)[0]["decision"], "joined")

    def test_normalized_content_can_continue_an_unrotated_table(self):
        a, b, layers = pair()
        for rotation in (90, 180, 270):
            layers[2].update(rotation=rotation, normalized=True)
            decision, _ = self.decide(a, b, layers)
            self.assertEqual(decision["decision"], "joined")
            self.assertEqual(decision["evidence"]["rotation"], [0, rotation])

    def test_page_without_text_layer_cannot_be_judged(self):
        a, b, layers = pair(words_b=[])
        decision, _ = self.decide(a, b, layers)
        self.assertEqual(decision["decision"], "separate")
        self.assertIn("no_text_layer", decision["reasons"])

    def test_numeric_series_that_restarts_blocks_the_join(self):
        grid_a = [HEADER] + [[f"S{i}", str(1000 + 100 * i), str(i)] for i in range(8)]
        grid_b = [HEADER] + [["S9", "10", "9"]] + body(10, 3)
        a, b, layers = pair(grid_a, grid_b)
        decision, _ = self.decide(a, b, layers)
        self.assertEqual(decision["decision"], "separate")
        self.assertIn("series_restarts", decision["reasons"])

    def test_numeric_series_that_continues_is_recorded(self):
        grid_a = [HEADER] + [[f"S{i}", str(1000 + 100 * i), "x"] for i in range(8)]
        grid_b = [HEADER] + [["S9", "1800", "y"], ["S10", "1900", "z"]]
        a, b, layers = pair(grid_a, grid_b)
        decision, _ = self.decide(a, b, layers)
        self.assertEqual(decision["decision"], "joined")
        self.assertIn("series_continues", decision["reasons"])

    def test_series_alone_is_not_a_continuation_signal(self):
        grid_a = [[f"S{i}", str(1000 + 100 * i), "x"] for i in range(8)]
        grid_b = [["S9", "1800", "y"], ["S10", "1900", "z"]]
        a, b, layers = pair(grid_a, grid_b, header_a=0, header_b=0)
        self.assertEqual(self.decide(a, b, layers)[0]["decision"], "uncertain")

    def test_table_already_spanning_two_pages_is_left_alone(self):
        a, b, layers = pair()
        b["regions"] = b["regions"] + [{"page": 3, "bbox": [50, 70, 500, 100]}]
        self.assertIn("already_multipage", self.decide(a, b, layers)[0]["reasons"])

    def test_empty_table_is_not_joined(self):
        a, b, layers = pair()
        b.update(grid=[], num_rows=0, cells=[], rows_text=[])
        self.assertIn("empty_table", self.decide(a, b, layers)[0]["reasons"])

    def test_header_cell_spanning_into_the_body_blocks_dropping_it(self):
        a, b, layers = pair()
        b["cells"][0]["row_span"] = 2
        decision, _ = self.decide(a, b, layers)
        self.assertEqual(decision["decision"], "separate")
        self.assertIn("header_cell_spans_body", decision["reasons"])

    def test_pages_that_are_not_consecutive_form_no_pair(self):
        a, b, layers = pair()
        b["regions"] = [{"page": 3, "bbox": b["regions"][0]["bbox"]}]
        self.assertEqual(plan([a, b], layers)["decisions"], [])
        self.assertEqual(candidate_pairs([a], set()), [])

    def test_document_without_tables_on_consecutive_pages_never_reads_the_pdf(self):
        a, _, _ = pair()

        def forbidden(number):
            raise AssertionError("the PDF must not be read")
        self.assertEqual(plan_joins([a], forbidden, 5, OPTIONS)["decisions"], [])

    def test_unreadable_pdf_is_reported_and_nothing_is_joined(self):
        a, b, _ = pair()

        def broken(number):
            raise OSError("cannot open")
        result = plan_joins([a, b], broken, 2, OPTIONS)
        self.assertEqual(result["groups"], [])
        self.assertEqual(result["decisions"][0]["reasons"], ["pdf_unreadable"])
        self.assertIn("OSError", result["error"])

    def test_footer_frame_table_does_not_hide_the_body_pair(self):
        a, b, layers = pair(top_a=560.0)
        frame = table(3, 1, [["Page", "1", "of 2"]], 0, 762.0)
        layers[1]["words"] += [dict(w, row=("f", 0)) for w in words_for(frame["grid"], 762.0)]
        footer = [{"text": "Page", "bbox": [50, 762, 80, 772], "row": 0}]
        layers[2]["words"] += [dict(w, row=("f", 0)) for w in footer]
        layers[1]["words"] += [dict(w, row=("f", 1)) for w in footer]
        result = plan([a, frame, b], layers)
        self.assertEqual([d["decision"] for d in result["decisions"]], ["joined"])

    def test_decisions_are_deterministic(self):
        a, b, layers = pair()
        self.assertEqual(json.dumps(plan([a, b], layers), sort_keys=True, default=str), json.dumps(plan([a, b], layers), sort_keys=True, default=str))


class HelperTests(unittest.TestCase):
    def test_number_parsing_and_header_like(self):
        self.assertEqual((number_of("1,234.5"), number_of("-7"), number_of("12 ft"), number_of("")), (1234.5, -7.0, None, None))
        self.assertIsNone(number_of("4 5"))  # two cells' worth of text is not the number 45
        self.assertTrue(header_like(HEADER))
        self.assertFalse(header_like(["Depth", "100"]))
        self.assertFalse(header_like(["", ""]))

    def test_leading_header_rows_never_takes_the_last_row_and_needs_column_order(self):
        a, b, _ = pair()
        self.assertEqual(leading_header_rows(a, b), 1)
        self.assertEqual(leading_header_rows(a, dict(b, grid=[HEADER])), 0)
        self.assertEqual(leading_header_rows(a, dict(b, grid=[HEADER[::-1], *b["grid"][1:]])), 0)

    def test_series_needs_enough_monotonic_rows(self):
        a = {"num_cols": 1, "header_rows": 0, "grid": [["1"], ["2"], ["3"]]}
        b = {"grid": [["4"]]}
        self.assertEqual(series_check(a, b, 0, OPTIONS), {"continues": [], "restarts": []})  # three rows are not enough
        a["grid"] = [[str(i)] for i in range(1, 8)]
        self.assertEqual(series_check(a, {"grid": [["8"]]}, 0, OPTIONS), {"continues": [0], "restarts": []})
        self.assertEqual(series_check(a, {"grid": [["2"]]}, 0, OPTIONS), {"continues": [], "restarts": [0]})

    def test_sample_pages_is_deterministic_and_includes_needed_pages(self):
        self.assertEqual(sample_pages(5, {2}, 10), [1, 2, 3, 4, 5])
        chosen = sample_pages(300, {17, 18}, 40)
        self.assertEqual(chosen, sample_pages(300, {17, 18}, 40))
        self.assertTrue({17, 18} <= set(chosen) and len(chosen) <= 40)

    def test_text_lines_group_words_by_row(self):
        lines = text_lines(words_for([["a", "b"], ["c", "d"]], 10.0))
        self.assertEqual([line["text"] for line in lines], ["a b", "c d"])


class ConfigTests(unittest.TestCase):
    def test_default_uses_source_proof_and_shipped_candidate_replays_the_looser_rule(self):
        self.assertEqual(validate_table_join(copy.deepcopy(OPTIONS)), OPTIONS)
        self.assertTrue(load_k1_config()["table_join"]["continuity"]["require_source_proof"])
        candidate = json.loads((ROOT / "configs/corpus/candidates/k1_table_join_candidate.json").read_text(encoding="utf-8"))
        self.assertEqual(candidate["table_join"], OPTIONS)
        self.assertEqual(validate_k1_config(candidate), candidate)

    def test_every_key_is_required_and_checked(self):
        def changed(mutate):
            options = copy.deepcopy(OPTIONS)
            mutate(options)
            return options
        bad = [lambda o: o.pop("sources"), lambda o: o.update(extra=1), lambda o: o["sources"].append("pdfminer"), lambda o: o.update(rotations=[45]),
               lambda o: o.update(rotations=[]), lambda o: o["page"].pop("frame_slack_pt"), lambda o: o["boundary"].update(word_slack_pt=-1),
               lambda o: o["running_text"].update(max_pages=0), lambda o: o["running_text"].update(min_pages_frac=0), lambda o: o["structure"].update(x_tolerance_rel="0.03"),
               lambda o: o["continuity"].update(series_min_rows=2.5), lambda o: o.update(sources=["docling", "docling"])]
        for mutate in bad:
            with self.assertRaises(ValueError):
                validate_table_join(changed(mutate))
        with self.assertRaises(ValueError):
            validate_k1_config({**load_k1_config(), "table_join": {}})


def apply(tables, layers, pages=2):
    result = plan(tables, layers, pages)
    return result, apply_groups(tables, result, OPTIONS)


class AssemblyTests(unittest.TestCase):
    def test_joined_table_keeps_the_first_id_and_records_every_part(self):
        a, b, layers = pair()
        c = table(3, 2, [["Other", "Table", "Here"], ["x", "1", "2"]], 1, 400.0)
        d = table(4, 3, body(1, 2), 0, 70.0)
        result, (tables, absorbed, failures) = apply([a, b], layers)
        self.assertEqual(failures, [])
        self.assertEqual([t["table_id"] for t in tables], [a["table_id"]])
        joined = tables[0]
        self.assertEqual(joined["join"]["status"], "joined")
        self.assertIn("header_repeated", joined["join"]["reasons"])
        self.assertEqual(joined["pages"], [1, 2])
        self.assertEqual(joined["num_rows"], len(a["grid"]) + len(b["grid"]) - 1)
        self.assertEqual(joined["grid"], a["grid"] + b["grid"][1:])
        self.assertEqual(joined["header_rows"], 1)
        self.assertEqual([(p["page"], p["row_start"], p["row_end"]) for p in joined["parts"]], [(1, 0, 9), (2, 9, 14)])
        self.assertEqual(joined["parts"][1]["header"], [HEADER])
        self.assertEqual(len(joined["regions"]), 2)
        self.assertEqual(absorbed[b["logical_id"]], {"table_id": b["table_id"], "owner": a["table_id"], "offset": 9, "dropped": 1, "rows": 5})
        self.assertEqual(c["table_id"], f"{FID}:t3")  # untouched fixtures: ids are never renumbered
        self.assertEqual(d["table_id"], f"{FID}:t4")

    def test_cells_rows_text_and_row_count_are_consistent_with_the_grid(self):
        a, b, layers = pair()
        _, (tables, _, _) = apply([a, b], layers)
        joined = tables[0]
        self.assertEqual(max(cell["r"] for cell in joined["cells"]) + 1, joined["num_rows"])
        self.assertEqual(len(joined["cells"]), len(a["cells"]) + len(b["cells"]) - len(b["grid"][0]))
        by_position = {(cell["r"], cell["c"]): cell["text"] for cell in joined["cells"]}
        self.assertTrue(all(by_position[(r, c)] == joined["grid"][r][c] for r, row in enumerate(joined["grid"]) for c in range(3)))
        self.assertEqual(len(joined["rows_text"]), joined["num_rows"] - joined["header_rows"])
        self.assertEqual(joined["rows_text"][-1], "Item: Row13; Plan: 230; Actual: 330")

    def test_orphaned_header_labels_the_rows_of_the_second_table(self):
        a, b, layers = pair(grid_a=[HEADER], grid_b=body(1, 3), header_a=1, header_b=0, top_a=700.0)
        _, (tables, _, _) = apply([a, b], layers)
        self.assertEqual(tables[0]["rows_text"][0], "Item: Row1; Plan: 110; Actual: 210")
        self.assertEqual(tables[0]["num_rows"], 4)

    def test_nothing_is_joined_for_uncertain_pairs_but_both_tables_say_so(self):
        a, b, layers = pair(grid_a=body(1, 8), grid_b=body(9, 5), header_a=0, header_b=0)
        _, (tables, absorbed, _) = apply([a, b], layers)
        self.assertEqual((len(tables), absorbed), (2, {}))
        self.assertEqual(tables[0]["join"]["status"], "uncertain")
        self.assertEqual(tables[0]["join"]["reasons"], [f"uncertain_next:{b['table_id']}:no_continuation_signal"])
        self.assertEqual(tables[1]["join"]["reasons"], [f"uncertain_previous:{a['table_id']}:no_continuation_signal"])
        self.assertEqual(tables[0]["grid"], a["grid"])

    def test_chain_of_three_pages_becomes_one_table(self):
        a, b, layers = pair()
        grid_c = [HEADER] + body(49, 4)
        c = table(3, 3, grid_c, 1, 70.0)
        layers[2] = layer(words_for(b["grid"], 70.0) + words_for([], 0))
        # page 2 holds table b all the way down so that it also ends the body of the page
        b = table(2, 2, [HEADER] + body(9, 40), 1, 70.0)
        b["regions"] = [{"page": 2, "bbox": [50.0, 70.0, 500.0, 720.0]}]
        layers[2] = layer(words_for(b["grid"], 70.0, step=15.0))
        layers[3] = layer(words_for(grid_c, 70.0))
        c["regions"] = [{"page": 3, "bbox": [50.0, 70.0, 500.0, 150.0]}]
        result, (tables, absorbed, failures) = apply([a, b, c], layers, pages=3)
        self.assertEqual(failures, [])
        self.assertEqual([len(g) for g in result["groups"]], [3])
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0]["pages"], [1, 2, 3])
        self.assertEqual(tables[0]["num_rows"], 9 + 40 + 4)
        self.assertEqual([p["row_start"] for p in tables[0]["parts"]], [0, 9, 49])
        self.assertEqual({e["owner"] for e in absorbed.values()}, {a["table_id"]})

    def test_no_text_is_lost_the_token_multiset_is_preserved(self):
        from graph_builder.corpus.table_join import token_bag
        a, b, layers = pair()
        _, (tables, _, _) = apply([a, b], layers)
        self.assertEqual(token_bag(tables[0]["grid"]) + token_bag(b["grid"][:1]), token_bag(a["grid"]) + token_bag(b["grid"]))

    def test_inconsistent_table_is_left_separate_and_reported(self):
        a, b, layers = pair()
        b["num_rows"] += 1  # the record disagrees with its own grid
        result, (tables, absorbed, failures) = apply([a, b], layers)
        self.assertEqual([t["table_id"] for t in tables], [a["table_id"], b["table_id"]])
        self.assertEqual(absorbed, {})
        self.assertEqual(failures[0]["reason"], "invariant_failed")
        self.assertEqual(result["decisions"][0]["decision"], "separate")

    def test_input_tables_are_not_mutated(self):
        a, b, layers = pair()
        before = copy.deepcopy([a, b])
        apply([a, b], layers)
        self.assertEqual([a, b], before)


class MapChildrenTests(unittest.TestCase):
    def chunks(self):
        def chunk(table_id, start, end, text):
            return dict(chunk_id="old", doc_id="doc", type="table", text=text, section=None, section_path=[], page=1, pages=[1], regions=[], source_spans=[],
                        table_id=table_id, row_start=start, row_end=end)
        return [chunk("doc#t0001", 1, 5, "A1"), chunk("doc#t0001", 5, 9, "A2"), chunk("doc#t0002", 1, 4, "B1"), chunk("doc#t0002", 4, 6, "B2")]

    def test_absorbed_chunks_are_parented_to_the_first_table_with_joined_row_numbers(self):
        a, b, layers = pair()
        _, (tables, absorbed, _) = apply([a, b], layers)
        moved: list[dict] = []
        children, parents = map_children(FID, "doc", "other", self.chunks(), tables, [], {}, absorbed=absorbed, moved=moved)
        self.assertEqual([c["chunk_id"] for c in children], [f"{FID}:t1:c{i}" for i in range(4)])
        self.assertEqual([(c["table_id"], c["row_start"], c["row_end"]) for c in children], [(a["table_id"], 1, 5), (a["table_id"], 5, 9), (a["table_id"], 9, 12), (a["table_id"], 12, 14)])
        self.assertEqual([c["text"] for c in children], ["A1", "A2", "B1", "B2"])
        self.assertEqual(moved, [dict(old_chunk_id=f"{FID}:t2:c0", new_chunk_id=f"{FID}:t1:c2", old_table_id=b["table_id"], new_table_id=a["table_id"]),
                                 dict(old_chunk_id=f"{FID}:t2:c1", new_chunk_id=f"{FID}:t1:c3", old_table_id=b["table_id"], new_table_id=a["table_id"])])
        self.assertEqual([p["parent_id"] for p in parents], [a["table_id"]])
        self.assertEqual(parents[0]["pages"], [1, 2])
        joined = "\n\n".join(c["text"] for c in children)
        self.assertTrue(all(joined[c["char_start"]:c["char_end"]] == c["text"] for c in children))

    def test_without_the_option_nothing_changes(self):
        a, b, _ = pair()
        children, parents = map_children(FID, "doc", "other", self.chunks(), [a, b], [], {})
        self.assertEqual([c["chunk_id"] for c in children], [f"{FID}:t1:c0", f"{FID}:t1:c1", f"{FID}:t2:c0", f"{FID}:t2:c1"])
        self.assertEqual([(c["row_start"], c["row_end"]) for c in children], [(1, 5), (5, 9), (1, 4), (4, 6)])

    def test_quarantine_findings_stay_with_the_chunks_of_their_own_part(self):
        a, b, layers = pair()
        _, (tables, absorbed, _) = apply([a, b], layers)
        moved: list[dict] = []
        children, _ = map_children(FID, "doc", "other", self.chunks(), tables, [], {}, absorbed=absorbed, moved=moved)
        owners = table_owners(tables, absorbed, children, moved)
        finding = {"table_id": b["logical_id"], "source_ref": b["parts"][0]["source_ref"], "reason": "table_geometry_inconsistent"}
        side = chunk_sidecar({"quarantine": {"findings": [finding]}}, children, owners)
        self.assertEqual(sorted(side["chunks"]), [f"{FID}:t1:c2", f"{FID}:t1:c3"])
        first = dict(finding, table_id=a["logical_id"], source_ref=a["parts"][0]["source_ref"])
        side = chunk_sidecar({"quarantine": {"findings": [first]}}, children, owners)
        self.assertEqual(sorted(side["chunks"]), [f"{FID}:t1:c0", f"{FID}:t1:c1"])


def draw_pdf(path: Path) -> None:
    """Three pages: a table whose header repeats on page 2 (a continuation), then page 3 with an unrelated table under a title."""
    document = fitz.open()
    for number in (1, 2, 3):
        page = document.new_page(width=WIDTH, height=HEIGHT)
        page.insert_text((50, 30), "Running header of the report", fontsize=9)
        page.insert_text((50, 780), "Running footer", fontsize=9)
    rows = [HEADER] + body(1, 8)
    for index, row in enumerate(rows):
        for c, cell in enumerate(row):
            document[0].insert_text((50 + 150 * c, 600 + 14 * index), cell, fontsize=9)
    for index, row in enumerate([HEADER] + body(9, 5)):
        for c, cell in enumerate(row):
            document[1].insert_text((50 + 150 * c, 90 + 14 * index), cell, fontsize=9)
    document[2].insert_text((50, 120), "A new section with its own table", fontsize=11)
    for index, row in enumerate([HEADER] + body(30, 3)):
        for c, cell in enumerate(row):
            document[2].insert_text((50 + 150 * c, 150 + 14 * index), cell, fontsize=9)
    document.save(path)
    document.close()


@unittest.skipIf(fitz is None, "PyMuPDF not available")
class RealPdfTests(unittest.TestCase):
    def test_join_tables_reads_the_pdf_text_layer(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "t.pdf"
            draw_pdf(pdf)
            from graph_builder.corpus.text_layer import source_page
            page = source_page(pdf, 1)
            top = min(w["bbox"][1] for w in page["words"] if w["text"] == "Item")
            bottom = max(w["bbox"][3] for w in page["words"] if w["text"] == "Row8")
            page2 = source_page(pdf, 2)
            top2 = min(w["bbox"][1] for w in page2["words"] if w["text"] == "Item")
            bottom2 = max(w["bbox"][3] for w in page2["words"] if w["text"] == "Row13")
            page3 = source_page(pdf, 3)
            top3 = min(w["bbox"][1] for w in page3["words"] if w["text"] == "Item")
            bottom3 = max(w["bbox"][3] for w in page3["words"] if w["text"] == "Row32")
            a, b, c = (table(1, 1, [HEADER] + body(1, 8), 1, top), table(2, 2, [HEADER] + body(9, 5), 1, top2),
                       table(3, 3, [HEADER] + body(30, 3), 1, top3))
            for t, (p, y0, y1) in zip((a, b, c), ((1, top, bottom), (2, top2, bottom2), (3, top3, bottom3))):
                t["regions"] = [{"page": p, "bbox": [49.0, y0 - 1, 49.0 + 450.0, y1 + 1]}]
            tables, absorbed, report = join_tables([a, b, c], pdf, 3, OPTIONS)
            decisions = {(d["a"], d["b"]): d for d in report["decisions"]}
            self.assertEqual(decisions[(a["table_id"], b["table_id"])]["decision"], "joined", decisions[(a["table_id"], b["table_id"])]["reasons"])
            self.assertEqual(decisions[(b["table_id"], c["table_id"])]["decision"], "separate")  # page 2 table does not end its page body, and page 3 has a title
            self.assertEqual([t["table_id"] for t in tables], [a["table_id"], c["table_id"]])
            self.assertEqual(tables[0]["pages"], [1, 2])
            self.assertEqual(json.dumps(report, sort_keys=True), json.dumps(join_tables([a, b, c], pdf, 3, OPTIONS)[2], sort_keys=True))

    def test_unexpected_error_in_one_document_leaves_its_tables_untouched(self):
        a, b, _ = pair()
        del b["regions"]  # a record the joiner cannot read
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "t.pdf"
            draw_pdf(pdf)
            tables, absorbed, report = join_tables([a, b], pdf, 2, OPTIONS)
        self.assertEqual((tables, absorbed), ([a, b], {}))
        self.assertIn("KeyError", report["summary"]["error"])

    def test_missing_pdf_never_fails_the_export(self):
        a, b, _ = pair()
        tables, absorbed, report = join_tables([a, b], Path("does-not-exist.pdf"), 2, OPTIONS)
        self.assertEqual((tables, absorbed), ([a, b], {}))
        self.assertIsNotNone(report["summary"]["error"])


if __name__ == "__main__":
    unittest.main()
