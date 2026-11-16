"""A-445: severity policy for lost list/outline numbers (owner direction D2) and the label-value false-alarm classes.

D2: the B3 downgrade of FIDELITY_ENUMERATOR_MARKERS_NOT_KEPT from WARN to INFO is withdrawn. Positive tests: a page that lost its
list or outline numbers is flagged WARN again, and a real lost number next to the markers still is. Negative tests: a page whose
numbers are kept raises nothing; an invalid severity in the config is rejected instead of silently hiding the class."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import shutil
import unittest

from graph_builder.corpus.qa import fidelity as fid
from graph_builder.corpus.qa.signals import Registry

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / "data" / "interim" / "overnight" / "b4" / "a445" / "test-tmp"  # git-ignored, inside the repository
CONFIG_PATH = ROOT / "configs/qa/source_fidelity.json"
CONFIG = fid.load_config(CONFIG_PATH)
OUTLINE = "16.3 Casing design\n16.4 Cement program\n16.5 Mud program\n"
PDF = OUTLINE + "Top of cement 1200 ft and the shoe at 2100 ft are planned for the surface casing string today\n"
K1_WITHOUT_NUMBERS = "Casing design\nCement program\nMud program\nTop of cement 1200 ft and the shoe at 2100 ft are planned for the surface casing string today\n"
K1_WITH_NUMBERS = OUTLINE + "Top of cement 1200 ft and the shoe at 2100 ft are planned for the surface casing string today\n"
BAD = ("WARN", "ERROR")


def severities(pdf: str, k1: str, config: dict, registry: Registry) -> dict[str, str]:
    raw = fid.compare_page(pdf, k1, "", "", config, "", fid.enumerator_items(pdf, config))
    return {code: registry.reasons[code].severity for code, _ in fid.judge(raw, "text", False, config)}


class MarkerSeverityPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = fid.register_fidelity(Registry(), config_path=CONFIG_PATH)

    def test_shipped_config_and_check_version(self) -> None:
        self.assertEqual(fid.marker_severity(CONFIG), "WARN")
        self.assertEqual(CONFIG["enumerators"]["marker_severity"]["value"], "WARN")
        self.assertEqual(fid.CHECK_VERSION, "4")  # bumped when the INFO downgrade was withdrawn

    def test_page_that_lost_its_numbers_is_flagged_warn(self) -> None:
        found = severities(PDF, K1_WITHOUT_NUMBERS, CONFIG, self.registry)
        self.assertEqual(found, {fid.MARKER_CODE: "WARN"})
        self.assertIn(found[fid.MARKER_CODE], BAD)

    def test_flat_list_and_appendix_numbers_are_flagged_warn_too(self) -> None:
        pdf = "Appendices\n1. AK-3 Targeting Report\n2. AK-3 Drilling Plan\n3. Permits\n"
        found = severities(pdf, "Appendices\nAK-3 Targeting Report\nAK-3 Drilling Plan\nPermits\n", CONFIG, self.registry)
        self.assertEqual(found[fid.MARKER_CODE], "WARN")  # (a page this short also gets the INFO "insufficient tokens")

    def test_real_lost_number_next_to_lost_markers_is_still_flagged(self) -> None:
        k1 = "Casing design\nCement program\nMud program\nTop of cement ft and the shoe at ft are planned for the surface casing string today\n"
        found = severities(PDF, k1, CONFIG, self.registry)
        self.assertEqual(found.get("FIDELITY_NUMERIC_RECALL_LOW"), "WARN")
        self.assertEqual(found.get(fid.MARKER_CODE), "WARN")

    def test_page_that_kept_its_numbers_raises_nothing(self) -> None:
        self.assertEqual(severities(PDF, K1_WITH_NUMBERS, CONFIG, self.registry), {})

    def test_single_leading_measurement_is_not_a_marker_and_still_numeric_warn(self) -> None:
        pdf = "8.5 in hole section drilled to the planned depth without any problem reported by the crew\n"
        found = severities(pdf, "in hole section drilled to the planned depth without any problem reported by the crew\n", CONFIG, self.registry)
        self.assertEqual(found, {"FIDELITY_NUMERIC_RECALL_LOW": "WARN"})

    def test_missing_severity_key_defaults_to_warn_not_info(self) -> None:
        config = copy.deepcopy(CONFIG)
        config["enumerators"].pop("marker_severity")
        self.assertEqual(fid.marker_severity(config), "WARN")
        self.assertEqual(fid.marker_severity({}), "WARN")  # an old config without the section: the check is off, the default is still WARN

    def test_invalid_severity_is_rejected(self) -> None:
        for bad in ("ERROR", "warn", "", None, 3):
            config = copy.deepcopy(CONFIG)
            config["enumerators"]["marker_severity"]["value"] = bad
            with self.assertRaises(ValueError):
                fid.marker_severity(config)

    def test_info_is_possible_only_by_an_explicit_config_value(self) -> None:
        shutil.rmtree(SCRATCH, ignore_errors=True)
        SCRATCH.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, SCRATCH, ignore_errors=True)
        config = copy.deepcopy(CONFIG)
        config["enumerators"]["marker_severity"]["value"] = "INFO"
        path = SCRATCH / "info.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        registry = fid.register_fidelity(Registry(), config_path=path)
        self.assertEqual(severities(PDF, K1_WITHOUT_NUMBERS, config, registry), {fid.MARKER_CODE: "INFO"})

    def test_other_reason_severities_are_unchanged(self) -> None:
        by_code = {code: severity for code, severity, _, _ in fid.REASONS}
        self.assertEqual({code: by_code[code] for code in ("FIDELITY_NUMERIC_NOVEL", "FIDELITY_NUMERIC_RECALL_LOW", "FIDELITY_WORD_RECALL_LOW", "FIDELITY_PAGE_EMPTY")},
                         {"FIDELITY_NUMERIC_NOVEL": "WARN", "FIDELITY_NUMERIC_RECALL_LOW": "WARN", "FIDELITY_WORD_RECALL_LOW": "WARN", "FIDELITY_PAGE_EMPTY": "WARN"})
        for code in ("FIDELITY_NOT_APPLICABLE", "FIDELITY_PARTIAL_REFERENCE", "FIDELITY_NO_REFERENCE", "FIDELITY_INSUFFICIENT_TOKENS", "FIDELITY_PAGE_EMPTY_EXPLAINED"):
            self.assertEqual(by_code[code], "INFO")


# ---- label-value checker false-alarm classes (A-441 gold: S005 URL scheme, S013 bracket index) ----
from graph_builder.corpus.qa import labelvalue as lv  # noqa: E402

LV_CONFIG = lv.load_config(ROOT / "configs/qa/label_value.json")
LV_OLD = copy.deepcopy(LV_CONFIG)  # the A-432 behaviour: no not_a_label_patterns key
LV_OLD["labels"].pop("not_a_label_patterns")


def lv_word(text: str, left: float, bottom: float, width: float = 40, height: float = 8) -> dict:
    return {"text": text, "l": left, "b": bottom, "r": left + width, "t": bottom + height}


def lv_pairs(words: list[dict], config: dict) -> dict[str, tuple[str, str]]:
    return {p["label"]: (p["value"], p["source"]) for p in lv.pdf_pairs(lv.phrases_of(words, config), config)}


class LabelValueFalseAlarmClassTests(unittest.TestCase):
    def test_version_bumped(self) -> None:
        self.assertEqual(lv.CHECK_VERSION, "2")

    def test_url_scheme_colon_is_not_a_label(self) -> None:
        words = [lv_word("http://cfpub.epa.gov/npdes/", 40, 600, 120)]
        self.assertEqual(lv_pairs(words, LV_CONFIG), {})
        self.assertIn("http", lv_pairs(words, LV_OLD))  # the old behaviour: a false label 'http'

    def test_a_genuine_label_whose_value_is_a_url_stays_a_pair(self) -> None:
        found = lv_pairs([lv_word("Website:", 40, 600, 40), lv_word("http://example.org/a", 84, 600, 100)], LV_CONFIG)
        self.assertEqual(found["website"][0], "http://example.org/a")
        inline = lv_pairs([lv_word("Source: http://example.org/a", 40, 600, 140)], LV_CONFIG)
        self.assertEqual(inline["source"], ("http://example.org/a", "inline"))

    def test_bracket_index_notation_is_not_a_label(self) -> None:
        for text in ("Main[3]:Up:S005", "Main[3]:Up", "Port[12]:"):
            self.assertEqual(lv_pairs([lv_word(text, 40, 600, 90)], LV_CONFIG), {}, text)
        self.assertNotEqual(lv_pairs([lv_word("Main[3]:Up:S005", 40, 600, 90)], LV_OLD), {})

    def test_labels_with_units_in_brackets_or_glued_values_stay_labels(self) -> None:
        self.assertIn("pressure[psi]", lv_pairs([lv_word("Pressure[psi]:", 40, 600, 60), lv_word("350", 110, 600, 20)], LV_CONFIG))
        self.assertEqual(lv_pairs([lv_word("Rig:Nabors", 40, 600, 60)], LV_CONFIG), {"rig": ("Nabors", "inline")})
        # a double-colon label ('Cutter:Inner/Outer:') is a real label of the RIMBase bit table: it must keep marking the end of the value of 'DepthOut:'
        self.assertEqual(lv_pairs([lv_word("Cutter:Inner/Outer:", 40, 600, 90)], LV_CONFIG), lv_pairs([lv_word("Cutter:Inner/Outer:", 40, 600, 90)], LV_OLD))
        self.assertIn("cutter", lv_pairs([lv_word("Cutter:Inner/Outer:", 40, 600, 90)], LV_CONFIG))

    def test_lv01_pattern_is_still_flagged_with_the_new_filters(self) -> None:
        words = [lv_word("Days", 40, 600, 20), lv_word("On", 62, 600, 10), lv_word("Location:", 74, 600, 40), lv_word("1", 180, 600, 5)]
        pdf = lv.pdf_pairs(lv.phrases_of(words, LV_CONFIG), LV_CONFIG)
        result = lv.compare_page(pdf, lv.k1_pairs("Days On Location: 1700", {p["label"] for p in pdf}), LV_CONFIG)
        self.assertEqual([m["k1_value"] for m in result["mismatches"]], ["1700"])
        right = lv.compare_page(pdf, lv.k1_pairs("Days On Location: 1", {p["label"] for p in pdf}), LV_CONFIG)
        self.assertEqual(right["mismatches"], [])

    def test_old_config_without_the_key_loads_and_runs(self) -> None:
        self.assertEqual(lv_pairs([lv_word("Days", 40, 600, 20), lv_word("Location:", 62, 600, 40), lv_word("1", 130, 600, 5)], LV_OLD), {"days location": ("1", "right")})


if __name__ == "__main__":
    unittest.main()