"""P1/P2 candidate tests: synthetic source layers only, never real extraction."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator

from graph_builder.corpus.form_recognition import labels_in_row, legacy_first, recognize, validate_form_recognition
from graph_builder.corpus.forms import extract_auto
from graph_builder.corpus.k1_build import build_document, map_children
from graph_builder.corpus.k1_config import load_k1_config, validate_k1_config
from graph_builder.corpus.k1_export import package_identity
from test_corpus_forms import TEMPLATE_LABELS, form_layer, layer, word

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "configs/corpus/candidates/k1_form_recognition_v1.json"
STANDARD_24NOV = ROOT / "configs/corpus/candidates/k1_standard_24nov.json"  # the profile main shipped on 24 November (D2/D4 decisions made the default smaller)
HEADER_ONLY = ROOT / "configs/corpus/candidates/k1_form_recognition_header_only.json"


def options():
    return {"version": "v1", "labels": {k: [k] for k in ("Alpha:", "Beta:", "Gamma:", "Delta:", "Echo:")},
            "geometry": {"label_start_gap_em": 1.0, "value_phrase_gap_em": 2.5, "row_gap_lines": 1.8},
            "eligibility": {"min_labels": 4, "min_rows": 2, "min_nonempty": 2},
            "excluded_titles": ["Operations Summary", "Management Summary", "Comments"],
            "table_headers": ["AFE No.", "AFE ($)", "Actual ($)"]}


def sample():
    words = []
    for i, name in enumerate(("Alpha:", "Beta:", "Gamma:", "Delta:")):
        words += [word(name, 10, 50, i, top=100 + 12 * i), word(str(i + 1), 65, 75, i, top=100 + 12 * i)]
    return layer(words, text="Independent source region")


def pairmap(fields):
    return [(f["key"], f["value"]) for f in fields]


def candidate_extract(source, configuration=None, **kwargs):
    with patch("graph_builder.corpus.forms.source_page", return_value=source):
        return extract_auto(Path("synthetic.pdf"), 1, TEMPLATE_LABELS,
                            recognition=options() if configuration is None else configuration, **kwargs)


class RecognitionTests(unittest.TestCase):
    def test_independent_region_without_operations_heading(self):
        found = []
        result = candidate_extract(sample(), recognition_findings=found)
        self.assertEqual(pairmap(result["fields"]), [("Alpha:", "1"), ("Beta:", "2"), ("Gamma:", "3"), ("Delta:", "4")])
        self.assertEqual((result["method"], result["verified"], result["template_label_share"]), ("generic", False, 0))
        self.assertEqual({r["attribution"] for r in found if r.get("reason") == "accepted"}, {"P2"})
        self.assertTrue(found[-1]["recognition_only"])

    def test_single_row_is_not_eligible(self):
        s = sample()
        for i, w in enumerate(s["words"]):
            w["row"] = 0
            w["bbox"] = [w["bbox"][0] + (i // 2) * 120, 100, w["bbox"][2] + (i // 2) * 120, 110]
        self.assertEqual(recognize(s, options())[0], [])

    def test_distinct_identity_count_not_occurrence_count(self):
        s = sample()
        for w in s["words"][::2]:
            w["text"] = "Alpha:"
        self.assertEqual(recognize(s, options())[0], [])

    def test_duplicate_label_occurrences_preserved(self):
        s = sample()
        s["words"] += [word("Alpha:", 10, 50, 4, 148), word("second", 65, 95, 4, 148)]
        fields, _ = recognize(s, options())
        self.assertEqual([p for p in pairmap(fields) if p[0] == "Alpha:"], [("Alpha:", "1"), ("Alpha:", "second")])

    def test_explicit_alias_preserves_source_spelling(self):
        o = options()
        o["labels"]["Alpha:"].append("AlphaValue:")
        s = sample(); s["words"][0]["text"] = "AlphaValue:"
        fields, _ = recognize(s, o)
        self.assertEqual(fields[0]["key"], "AlphaValue:")
        self.assertIsNone(fields[0]["canonical_key"])

    def test_no_fuzzy_or_case_matching(self):
        for spelling in ("alpha:", "Alph:", "Alpha", "Alpha;"):
            s = sample(); s["words"][0]["text"] = spelling
            self.assertEqual(recognize(s, options())[0], [])

    def test_longest_label_and_overlapping_alias_abstention(self):
        o = options(); o["labels"] = {"Long Label:": ["Long Label:"], "Long": ["Long"], "Label:": ["Label:"]}
        row = [word("Long", 10, 30, 0), word("Label:", 32, 60, 0)]
        labels, ambiguous = labels_in_row(row, o)
        self.assertFalse(ambiguous)
        self.assertEqual(labels[0]["identity"], "Long Label:")
        row[1]["bbox"] = [45, 100, 75, 110]
        self.assertEqual(labels_in_row(row, o), ([], True))

    def test_narrative_mentions_are_not_labels(self):
        s = sample()
        s["words"] += [word("Discuss", 0, 8, i, 100 + 12 * i) for i in range(4)]
        self.assertEqual(recognize(s, options())[0], [])

    def test_free_narrative_section_is_excluded(self):
        s = sample(); s["words"] += [word("Management Summary", 230, 370, -1, 80)]
        fields, reasons = recognize(s, options())
        self.assertEqual(fields, [])
        self.assertTrue(any(r["reason"] == "excluded_narrative_region" for r in reasons))

    def test_nonempty_threshold_and_proven_blank(self):
        s = sample()
        s["words"] = [w for w in s["words"] if not (w["row"] == 1 and w["text"] == "2")]
        s["rulings"] = [[0, 111, 100, 111.5], [0, 123, 100, 123.5], [100, 111, 100.5, 123.5]]
        fields, _ = recognize(s, options())
        self.assertIn(("Beta:", ""), pairmap(fields))
        self.assertIsNone(next(f for f in fields if f["key"] == "Beta:")["value_bbox"])
        o = options(); o["eligibility"]["min_nonempty"] = 4
        self.assertEqual(recognize(s, o)[0], [])

    def test_unbounded_empty_abstains(self):
        s = sample(); s["words"] = [w for w in s["words"] if w["text"] != "2"]
        fields, reasons = recognize(s, options())
        self.assertEqual(fields, [])
        self.assertTrue(any(r["reason"] == "empty_value_not_proven" for r in reasons))

    def test_empty_field_does_not_take_adjacent_afe_value(self):
        s = layer([word("Alpha:", 10, 50, 0), word("---", 120, 135, 0)],
                  [[0, 90, 200, 90.5], [0, 115, 200, 115.5], [100, 90, 100.5, 115.5]], text="header")
        old = dict(fields=[], header_boundary=200, method="rimbase_template")
        fields, _ = recognize(s, options(), old, [[110, 90, 200, 115]])
        self.assertEqual(pairmap(fields), [("Alpha:", "")])

    def test_afe_header_mask_and_unproven_adjacent_value(self):
        s = sample()
        s["words"] += [word("AFE", 60, 85, -1, 85), word("($)", 87, 102, -1, 85)]
        fields, reasons = recognize(s, options())
        self.assertEqual(fields, [])
        self.assertTrue(any(r["reason"] == "table_region" for r in reasons))

    def test_known_table_mask_vetoes_region(self):
        self.assertEqual(recognize(sample(), options(), excluded_boxes=[[0, 90, 100, 150]])[0], [])

    def test_one_row_table_with_registered_column_headers(self):
        s = layer([word("Alpha:", 10, 50, 0), word("Beta:", 120, 160, 0),
                   word("1", 10, 20, 1, 112), word("2", 120, 130, 1, 112)], text="table")
        fields, reasons = recognize(s, options(), dict(fields=[], method="rimbase_template", header_boundary=300))
        self.assertEqual(fields, [])
        self.assertTrue(any(r["reason"] == "table_region" for r in reasons))

    def test_unruled_unknown_headers_exclude_body(self):
        s = sample()
        s["words"] += [word("Description", 10, 50, -1, 85), word("Reading", 65, 95, -1, 85)]
        fields, reasons = recognize(s, options())
        self.assertEqual(fields, [])
        self.assertTrue(any(r["reason"] == "table_region" for r in reasons))

    def test_mixed_page_retains_independent_form_region(self):
        s = sample()
        s["words"] += [word("Alpha:", 10, 50, 8, 300), word("Beta:", 120, 160, 8, 300),
                       word("7", 10, 20, 9, 312), word("8", 120, 130, 9, 312)]
        fields, _ = recognize(s, options())
        self.assertEqual(len(fields), 4)
        self.assertTrue(all(f["key_bbox"][1] < 200 for f in fields))

    def test_ambiguous_value_rejects_region(self):
        s = sample(); s["words"] += [word("extra", 180, 210, 1, 112)]
        fields, reasons = recognize(s, options())
        self.assertEqual(fields, [])
        self.assertTrue(any(r["reason"] == "multiple_value_phrases" for r in reasons))

    def test_unsupported_multiline_is_not_truncated(self):
        s = sample(); s["words"] += [word("continued", 65, 110, 5, 150)]
        fields, reasons = recognize(s, options())
        self.assertEqual(fields, [])
        self.assertTrue(any(r["reason"] == "unsupported_multiline_value" for r in reasons))

    def test_independent_regions_cannot_pool_evidence(self):
        s = sample()
        for w in s["words"]:
            if w["row"] >= 2:
                w["bbox"][1] += 100; w["bbox"][3] += 100
        self.assertEqual(recognize(s, options())[0], [])

    def test_invalid_geometry_abstains(self):
        for invalid in ([1, 1, 1, 2], [0, 0, float("nan"), 2]):
            s = sample(); s["words"][0]["bbox"] = invalid
            self.assertEqual(recognize(s, options())[1][0]["reason"], "invalid_source_geometry")
        self.assertEqual(recognize(sample(), options(), excluded_boxes=[[0, 0, 0, 1]])[0], [])

    def test_p1_addition_preserves_existing_objects(self):
        s = sample()
        old_field = dict(key="Original:", value="  unchanged  ", key_bbox=[250, 50, 300, 60], value_bbox=[320, 50, 400, 60], verified=True)
        old = dict(fields=[old_field], header_boundary=200, method="rimbase_template")
        before = copy.deepcopy(old)
        additions, findings = recognize(s, options(), old)
        self.assertEqual(len(additions), 4)
        self.assertEqual(old, before)
        self.assertIs(old["fields"][0], old_field)
        self.assertEqual({r["attribution"] for r in findings if r.get("reason") == "accepted"}, {"P1"})

    def test_same_source_label_not_emitted_twice(self):
        s = sample(); existing = dict(key="Alpha:", value="1", key_bbox=[10, 100, 50, 110], value_bbox=[65, 100, 75, 110])
        additions, _ = recognize(s, options(), dict(fields=[existing], header_boundary=200, method="rimbase_template"))
        self.assertEqual([f["key"] for f in additions], ["Beta:", "Gamma:", "Delta:"])

    def test_candidate_cannot_steal_existing_value(self):
        s = sample(); existing = dict(key="Other:", value="Alpha: 1", key_bbox=[200, 100, 240, 110], value_bbox=[10, 100, 75, 110])
        additions, findings = recognize(s, options(), dict(fields=[existing], header_boundary=200, method="rimbase_template"))
        self.assertNotIn("Alpha:", [f["key"] for f in additions])
        self.assertTrue(any(r["reason"] == "overlaps_legacy_field" for r in findings))

    def test_deterministic_and_input_immutable(self):
        s = sample(); before = copy.deepcopy(s)
        first = recognize(s, options())
        self.assertEqual(first, recognize(s, options()))
        self.assertEqual(s, before)

    def test_translation_and_scale_do_not_change_pairs(self):
        first = recognize(sample(), options())[0]
        s = sample()
        for w in s["words"]:
            w["bbox"] = [v * 1.5 + 20 for v in w["bbox"]]
        s["width"] *= 2; s["height"] *= 2
        self.assertEqual(pairmap(first), pairmap(recognize(s, options())[0]))


class LocalBoundaryTests(unittest.TestCase):
    @staticmethod
    def table(top, first_row):
        return [word("Alpha:", 10, 50, first_row, top), word("Beta:", 120, 160, first_row, top),
                word("7", 10, 20, first_row + 1, top + 12), word("8", 120, 130, first_row + 1, top + 12)]

    def test_distant_table_before_form(self):
        s = sample()
        s["words"] += self.table(10, -2)
        fields, _ = recognize(s, options())
        self.assertEqual(pairmap(fields), pairmap(recognize(sample(), options())[0]))

    def test_adjacent_table_after_form_stays_excluded(self):
        s = sample()
        s["words"] += self.table(152, 4)
        fields, _ = recognize(s, options())
        self.assertEqual(pairmap(fields), pairmap(recognize(sample(), options())[0]))
        self.assertTrue(all(f["key_bbox"][1] < 152 for f in fields))

    def test_separator_bounds_adjacent_table_before_form(self):
        s = sample()
        s["words"] += self.table(70, -2)
        s["rulings"] = [[0, 96, 600, 96.5]]
        fields, _ = recognize(s, options())
        self.assertEqual(len(fields), 4)
        self.assertTrue(all(f["key_bbox"][1] >= 100 for f in fields))

    def test_no_proven_separator_after_table_abstains(self):
        s = sample()
        s["words"] += self.table(70, -2)
        fields, reasons = recognize(s, options())
        self.assertEqual(fields, [])
        self.assertTrue(any(r["reason"] == "table_region" for r in reasons))

    def test_interleaved_table_mask_does_not_pool_form_fragments(self):
        fields, reasons = recognize(sample(), options(), excluded_boxes=[[0, 111, 100, 123]])
        self.assertEqual(fields, [])
        self.assertTrue(any(r["reason"] == "table_region" for r in reasons))

    def test_large_gap_stops_unlabelled_continuation_inspection(self):
        s = sample()
        s["words"] += [word("distant", 65, 110, 4, 300)]
        fields, _ = recognize(s, options())
        self.assertEqual(len(fields), 4)
        self.assertTrue(all("distant" not in f["value"] for f in fields))

    def test_separator_stops_continuation_but_near_text_still_abstains(self):
        s = sample()
        s["words"] += [word("continued", 65, 110, 4, 154)]
        self.assertEqual(recognize(s, options())[0], [])
        s["rulings"] = [[0, 150, 600, 150.5]]
        fields, _ = recognize(s, options())
        self.assertEqual(len(fields), 4)
        self.assertTrue(all("continued" not in f["value"] for f in fields))

    def test_unruled_single_record_table_after_form(self):
        s = sample()
        s["words"] += [word("Column", 10, 50, 4, 152), word("Measure", 120, 165, 4, 152),
                       word("item", 10, 30, 5, 164), word("reading", 120, 160, 5, 164)]
        fields, _ = recognize(s, options())
        self.assertEqual(pairmap(fields), pairmap(recognize(sample(), options())[0]))

    def test_overlapping_external_table_mask_never_becomes_a_form(self):
        fields, _ = recognize(sample(), options(), excluded_boxes=[[45, 90, 90, 160]])
        self.assertEqual(fields, [])


class ConfigurationTests(unittest.TestCase):
    def test_separate_candidate_valid_and_default_absent(self):
        base = load_k1_config(STANDARD_24NOV)
        candidate = load_k1_config(CANDIDATE)
        self.assertNotIn("form_recognition", base)
        self.assertEqual({k: v for k, v in candidate.items() if k != "form_recognition"}, base)
        self.assertNotEqual(package_identity("a" * 64, base), package_identity("a" * 64, candidate))
        changed = copy.deepcopy(candidate); changed["form_recognition"]["geometry"]["row_gap_lines"] = 1.7
        self.assertNotEqual(package_identity("a" * 64, candidate), package_identity("a" * 64, changed))

    def test_unknown_keys_and_unsafe_thresholds_rejected(self):
        mutations = [lambda o: o.update(unknown=1), lambda o: o.update(version="v2"),
                     lambda o: o["geometry"].update(unknown=1), lambda o: o["eligibility"].update(unknown=1),
                     lambda o: o["eligibility"].update(min_labels=3), lambda o: o["eligibility"].update(min_rows=True),
                     lambda o: o["eligibility"].update(min_nonempty=1), lambda o: o["geometry"].update(row_gap_lines=float("nan")),
                     lambda o: o["geometry"].update(row_gap_lines=float("inf")), lambda o: o["geometry"].update(row_gap_lines=0),
                     lambda o: o["geometry"].update(row_gap_lines=True), lambda o: o["geometry"].update(row_gap_lines=5),
                     lambda o: o.update(labels={}), lambda o: o.update(excluded_titles=[])]
        for mutate in mutations:
            o = options(); mutate(o)
            with self.assertRaises(ValueError):
                validate_form_recognition(o)

    def test_alias_collisions_rejected(self):
        for spelling in ("Alpha:", "  Alpha: "):
            o = options(); o["labels"]["Beta:"].append(spelling)
            with self.assertRaises(ValueError):
                validate_form_recognition(o)

    def test_blocks_combination_rejected_before_source_access(self):
        config = load_k1_config(CANDIDATE)
        config["form_blocks"] = json.loads((ROOT / "configs/corpus/form_blocks.json").read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            validate_k1_config(config)
        with patch("graph_builder.corpus.forms.source_page", side_effect=AssertionError("source accessed")):
            with self.assertRaises(ValueError):
                extract_auto(Path("synthetic.pdf"), 1, TEMPLATE_LABELS, blocks=config["form_blocks"], recognition=options())


class IntegrationTests(unittest.TestCase):
    def test_default_none_is_byte_identical_and_does_not_load_candidate(self):
        for source in (sample(), form_layer(), layer([], text="")):
            with patch("graph_builder.corpus.forms.source_page", return_value=source), patch("graph_builder.corpus.form_recognition.recognize", side_effect=AssertionError("candidate used")):
                a = extract_auto(Path("synthetic.pdf"), 1, TEMPLATE_LABELS)
                b = extract_auto(Path("synthetic.pdf"), 1, TEMPLATE_LABELS, recognition=None)
                self.assertEqual(json.dumps(a, sort_keys=True).encode(), json.dumps(b, sort_keys=True).encode())

    def test_append_keeps_legacy_objects_and_metadata(self):
        from graph_builder.corpus.form_recognition import append_candidate
        old = dict(fields=[dict(key="Old:", value="x", key_bbox=[200, 10, 240, 20], value_bbox=[250, 10, 270, 20])], header_boundary=200, method="rimbase_template", verified=True)
        out = append_candidate(sample(), options(), old, .7, .4, 1, [])
        self.assertIs(out["fields"][0], old["fields"][0])
        self.assertEqual({k: v for k, v in out.items() if k != "fields"}, {k: v for k, v in old.items() if k != "fields"})

    def test_existing_forms_keep_ids_when_new_form_is_on_earlier_page(self):
        old_form = dict(candidate_extract(sample()), page=5)
        new_form = dict(candidate_extract(sample()), page=1)
        ordered = legacy_first([new_form, old_form], [{"page": 1, "recognition_only": True}])
        children, parents = map_children("f" + "0" * 16, "synthetic", "other", [], [], ordered, {})
        self.assertEqual([f["page"] for f in ordered], [5, 1])
        self.assertEqual([f["form_id"] for f in ordered], ["f" + "0" * 16 + ":f1", "f" + "0" * 16 + ":f2"])
        for name, records in (("form", ordered), ("chunk", children), ("parent", parents)):
            validator = Draft202012Validator(json.loads((ROOT / f"schemas/k1_{name}.schema.json").read_text()))
            for record in records:
                self.assertEqual(list(validator.iter_errors(record)), [])
        joined = "\n\n".join(c["text"] for c in children)
        for child in children:
            self.assertEqual(joined[child["char_start"]:child["char_end"]], child["text"])
            self.assertEqual(hashlib.sha256(child["text"].encode()).hexdigest(), child["sha256"])

    def test_builder_integrates_masks_context_isolation_and_sidecar(self):
        config = dict(load_k1_config(), form_recognition=options(), evidence_routing=False)
        sources = {1: sample(), 2: form_layer()}
        record = {"pages": [{"page": 1}, {"page": 2}], "statistics": {}}
        corpus = SimpleNamespace(config={"chunking": {"max_chars": 1500}, "table_mode": "fast"}, blob=lambda _: Path("synthetic.pdf"))
        doc = dict(doc_id="synthetic", sha256="0" * 64, original_name="synthetic.pdf", license_id="test", license_url=None)
        def source(_, number, **kwargs):
            return sources[number]
        with patch("graph_builder.corpus.k1_build.output_directory", return_value=Path("synthetic")), \
             patch.object(Path, "read_text", return_value=json.dumps(record)), \
             patch("graph_builder.corpus.k1_build.read_jsonl", return_value=[]), \
             patch("graph_builder.corpus.k1_build.load_template", return_value=TEMPLATE_LABELS), \
             patch("graph_builder.corpus.forms.source_page", side_effect=source), \
             patch("graph_builder.corpus.k1_build.report_contexts", return_value=({}, [], [])) as contexts, \
             patch("graph_builder.corpus.k1_build.page_records", return_value=[]):
            built = build_document(corpus, doc, "unused", config)
        self.assertEqual([f["page"] for f in built["forms"]], [2, 1])
        self.assertEqual(set(contexts.call_args.args[2]), {2})
        self.assertIn("form_recognition", built)
        self.assertTrue(all("form_recognition" not in f for f in built["forms"]))
        self.assertEqual({r["attribution"] for r in built["form_recognition"]["decisions"] if r.get("reason") == "accepted"}, {"P2"})


def header_only(**changes):
    o = options(); o["non_header_regions"] = False; o.update(changes)
    return o


def template_page(boundary):
    return dict(fields=[], method="rimbase_template", header_boundary=boundary)


def two_regions():
    """The same four labels twice: rows 0-3 near the top and rows 4-7 far below, separated by a large gap."""
    words = []
    for block, top in enumerate((100, 400)):
        for i, name in enumerate(("Alpha:", "Beta:", "Gamma:", "Delta:")):
            words += [word(name, 10, 50, 4 * block + i, top=top + 12 * i), word(str(i + 1), 65, 75, 4 * block + i, top=top + 12 * i)]
    return layer(words, text="Two source regions")


def three_labels():
    s = sample()
    s["words"] = s["words"][:6]
    return s


def dump(value):
    return json.dumps(value, sort_keys=True).encode()


def accepted(findings):
    return {r["attribution"] for r in findings if r.get("reason") == "accepted"}


def p1_only(findings):
    return [r for r in findings if r.get("attribution") != "P2" and r.get("reason") != "insufficient_region_evidence"]


class NonHeaderRegionsTests(unittest.TestCase):
    """The optional non_header_regions key separates header fields (P1) from region fields (P2)."""
    SCENARIOS = {"A": lambda: (sample(), template_page(200)), "B": lambda: (sample(), template_page(50)), "C": lambda: (sample(), None)}

    def test_absent_key_keeps_current_behaviour_and_equals_true(self):
        expected = {"A": "P1", "B": "P2", "C": "P2"}
        for name, make in self.SCENARIOS.items():
            with self.subTest(name):
                source, legacy = make()
                additions, findings = recognize(source, options(), legacy)
                self.assertEqual(pairmap(additions), [("Alpha:", "1"), ("Beta:", "2"), ("Gamma:", "3"), ("Delta:", "4")])
                self.assertEqual(accepted(findings), {expected[name]})
                self.assertEqual([r["field_index"] for r in findings if r.get("reason") == "accepted"], [0, 1, 2, 3])
                explicit = dict(options(), non_header_regions=True)
                source, legacy = make()
                self.assertEqual(dump(recognize(source, explicit, legacy)), dump((additions, findings)))

    def test_false_keeps_header_fields_byte_identical(self):
        source, legacy = self.SCENARIOS["A"]()
        combined = recognize(source, options(), legacy)
        source, legacy = self.SCENARIOS["A"]()
        only = recognize(source, header_only(), legacy)
        self.assertEqual(dump(only), dump(combined))
        self.assertEqual(accepted(only[1]), {"P1"})

    def test_false_removes_only_the_non_header_part_of_a_mixed_page(self):
        combined = recognize(two_regions(), options(), template_page(200))
        only = recognize(two_regions(), header_only(), template_page(200))
        self.assertEqual(accepted(combined[1]), {"P1", "P2"})
        self.assertEqual(len(combined[0]), 8)
        self.assertEqual(accepted(only[1]), {"P1"})
        self.assertEqual(dump(only[0]), dump(combined[0][:4]))
        self.assertEqual(dump(only[1]), dump(p1_only(combined[1])))

    def test_false_disables_fields_forms_and_findings_outside_the_header(self):
        for name in ("B", "C"):
            with self.subTest(name):
                source, legacy = self.SCENARIOS[name]()
                additions, findings = recognize(source, header_only(), legacy)
                self.assertEqual(additions, [])
                self.assertEqual([r for r in findings if r.get("reason") in ("accepted", "insufficient_region_evidence")], [])
                self.assertEqual(accepted(findings), set())
        found = []
        self.assertIsNone(candidate_extract(sample(), header_only(), recognition_findings=found))
        self.assertEqual(found, [{"page": 1, "legacy_field_count": 0, "recognition_only": False}])
        self.assertEqual(legacy_first([{"page": 1}], found), [{"page": 1}])

    def test_false_records_no_eligibility_finding_for_weak_regions(self):
        _, combined = recognize(three_labels(), options(), None)
        self.assertEqual([r["reason"] for r in combined], ["insufficient_region_evidence"])
        self.assertEqual(recognize(three_labels(), header_only(), None), ([], []))

    def test_false_still_reports_findings_that_are_not_region_evidence(self):
        s = sample(); s["words"][1]["bbox"] = [51, 100, 75, 110]
        combined = recognize(s, options(), template_page(200))[1]
        only = recognize(s, header_only(), template_page(200))[1]
        self.assertIn("insufficient_region_evidence", [r["reason"] for r in combined])
        self.assertEqual(only, [r for r in combined if r["reason"] != "insufficient_region_evidence"])
        self.assertEqual(only[0]["reason"], "no_label_value_separation")

    def test_inputs_are_not_mutated_and_result_is_deterministic(self):
        source, legacy = sample(), template_page(200)
        before, legacy_before = copy.deepcopy(source), copy.deepcopy(legacy)
        first = recognize(source, header_only(), legacy)
        self.assertEqual(first, recognize(source, header_only(), legacy))
        self.assertEqual((source, legacy), (before, legacy_before))

    def test_non_boolean_values_are_rejected(self):
        for bad in (0, 1, 0.0, "false", "true", None, [], {}, [False]):
            with self.subTest(repr(bad)):
                o = dict(options(), non_header_regions=bad)
                with self.assertRaisesRegex(ValueError, "non_header_regions"):
                    validate_form_recognition(o)
                with self.assertRaises(ValueError):
                    recognize(sample(), o, template_page(200))
                config = load_k1_config(); config["form_recognition"] = o
                with self.assertRaises(ValueError):
                    validate_k1_config(config)

    def test_unknown_and_missing_keys_are_still_rejected(self):
        for value in (True, False):
            o = header_only(); o["non_header_regions"] = value; o["unknown"] = 1
            with self.assertRaises(ValueError):
                validate_form_recognition(o)
            for required in ("version", "labels", "geometry", "eligibility", "excluded_titles", "table_headers"):
                o = dict(options(), non_header_regions=value); del o[required]
                with self.assertRaises(ValueError):
                    validate_form_recognition(o)
            validate_form_recognition(dict(options(), non_header_regions=value))

    def test_header_only_candidate_differs_from_v1_only_by_the_option(self):
        v1, header = load_k1_config(CANDIDATE), load_k1_config(HEADER_ONLY)
        self.assertIs(header["form_recognition"]["non_header_regions"], False)
        self.assertNotIn("non_header_regions", v1["form_recognition"])
        trimmed = copy.deepcopy(header); del trimmed["form_recognition"]["non_header_regions"]
        self.assertEqual(trimmed, v1)
        validate_k1_config(header)
        raw = json.loads(HEADER_ONLY.read_text(encoding="utf-8"))
        self.assertEqual({k: v for k, v in raw.items() if k != "form_recognition"}, load_k1_config(STANDARD_24NOV))

    def test_package_identity_changes_with_the_key_and_not_without_it(self):
        v1, header = load_k1_config(CANDIDATE), load_k1_config(HEADER_ONLY)
        explicit = copy.deepcopy(v1); explicit["form_recognition"]["non_header_regions"] = True
        identities = {package_identity("a" * 64, c) for c in (load_k1_config(), v1, header, explicit)}
        self.assertEqual(len(identities), 4)
        trimmed = copy.deepcopy(header); del trimmed["form_recognition"]["non_header_regions"]
        self.assertEqual(package_identity("a" * 64, trimmed), package_identity("a" * 64, v1))
        self.assertEqual(package_identity("a" * 64, v1), package_identity("a" * 64, load_k1_config(CANDIDATE)))

    def test_default_configurations_do_not_enable_form_recognition(self):
        for name in ("k1.json", "default.json"):
            text = (ROOT / "configs/corpus" / name).read_text(encoding="utf-8")
            self.assertNotIn("form_recognition", text)
            self.assertNotIn("non_header_regions", text)
        self.assertNotIn("form_recognition", load_k1_config())

    def test_header_only_cannot_be_combined_with_form_blocks(self):
        config = load_k1_config(HEADER_ONLY)
        config["form_blocks"] = json.loads((ROOT / "configs/corpus/form_blocks.json").read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            validate_k1_config(config)
        with patch("graph_builder.corpus.forms.source_page", side_effect=AssertionError("source accessed")):
            with self.assertRaises(ValueError):
                extract_auto(Path("synthetic.pdf"), 1, TEMPLATE_LABELS, blocks=config["form_blocks"], recognition=header_only())

    def test_builder_without_non_header_regions_creates_no_new_form(self):
        results = {}
        for name, recognition in (("combined", options()), ("header_only", header_only())):
            config = dict(load_k1_config(), form_recognition=recognition, evidence_routing=False)
            sources = {1: sample(), 2: form_layer()}
            record = {"pages": [{"page": 1}, {"page": 2}], "statistics": {}}
            corpus = SimpleNamespace(config={"chunking": {"max_chars": 1500}, "table_mode": "fast"}, blob=lambda _: Path("synthetic.pdf"))
            doc = dict(doc_id="synthetic", sha256="0" * 64, original_name="synthetic.pdf", license_id="test", license_url=None)
            with patch("graph_builder.corpus.k1_build.output_directory", return_value=Path("synthetic")), \
                 patch.object(Path, "read_text", return_value=json.dumps(record)), \
                 patch("graph_builder.corpus.k1_build.read_jsonl", return_value=[]), \
                 patch("graph_builder.corpus.k1_build.load_template", return_value=TEMPLATE_LABELS), \
                 patch("graph_builder.corpus.forms.source_page", side_effect=lambda _, number, **kwargs: sources[number]), \
                 patch("graph_builder.corpus.k1_build.report_contexts", return_value=({}, [], [])), \
                 patch("graph_builder.corpus.k1_build.page_records", return_value=[]):
                results[name] = build_document(corpus, doc, "unused", config)
        self.assertEqual([f["page"] for f in results["combined"]["forms"]], [2, 1])
        self.assertEqual([f["page"] for f in results["header_only"]["forms"]], [2])
        self.assertEqual(accepted(results["header_only"]["form_recognition"]["decisions"]), set())
        self.assertEqual(results["header_only"]["form_recognition"]["version"], "v1")


if __name__ == "__main__":
    unittest.main()
