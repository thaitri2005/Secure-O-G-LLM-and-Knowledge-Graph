"""A-444: none of the optional feature flags is enabled by the shared default configuration (K1 v1 defaults are frozen)."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from graph_builder.corpus.config import load_config
from graph_builder.corpus.k1_config import load_k1_config

ROOT = Path(__file__).resolve().parents[1]
CORPUS_OPTIONS = (("chunking", "table_markdown"), ("filters", "running_line_position_tolerance"),
                  ("filters", "running_line_min_pages"), ("filters", "toc_leader_min_dots"), ("analysis", "page_orientation"),
                  ("chunking", "label_value"), ("chunking", "quarantine"), ("chunking", "preserve_list_markers"))
# section_context is on in the shared default since the D2 decision (Track A log A-D07); the others stay opt-in
K1_OPTIONS = ("form_blocks", "report_boundaries", "form_recognition", "document_context")


def read(name: str) -> dict:
    return json.loads((ROOT / "configs" / "corpus" / name).read_text(encoding="utf-8-sig"))


class OptionsAreOffByDefaultTests(unittest.TestCase):
    def test_corpus_default_file_has_no_option_key(self) -> None:
        default = read("default.json")
        for section, key in CORPUS_OPTIONS:
            self.assertNotIn(key, default[section], f"{section}.{key} must stay opt-in")

    def test_loaded_corpus_configuration_has_no_option_key(self) -> None:
        loaded = load_config(ROOT / "configs" / "corpus" / "default.json")
        for section, key in CORPUS_OPTIONS:
            self.assertNotIn(key, loaded[section])

    def test_corpus_default_has_no_top_level_cache_key(self) -> None:
        """C-04: cache.code_version (code version in the fingerprint) is opt-in; the shared default keeps old fingerprints."""
        self.assertNotIn("cache", read("default.json"))
        self.assertNotIn("cache", load_config(ROOT / "configs" / "corpus" / "default.json"))

    def test_k1_default_file_and_loaded_configuration_have_no_option_key(self) -> None:
        raw, loaded = read("k1.json"), load_k1_config()
        for key in K1_OPTIONS:
            self.assertNotIn(key, raw, f"{key} must stay opt-in")
            self.assertNotIn(key, loaded)

    def test_k1_default_follows_the_d2_decisions(self) -> None:
        """Track A log A-D07: the 24 November groups measured on the demo release and kept off; grid recovery stays on."""
        raw = read("k1.json")
        for key in ("evidence_routing", "repair_numeric_cells", "numeric_cell_focus", "repair_native_column_alignment",
                    "repair_scan_table_ink", "recover_scan_grids"):
            self.assertIs(raw[key], False, key)
        self.assertIs(raw["forms"]["daily_header"], False)
        self.assertIs(raw["forms"]["missing_report_fields"], False)
        self.assertEqual(set(raw["table_rules"]), {"operations_summary", "ruled_panels"})
        for key in ("recover_source_grids", "recover_complex_grids", "recover_borderless_grids"):
            self.assertIs(raw[key], True, key)
        self.assertIn("table_join", raw)
        self.assertEqual(read("candidates/k1_standard_24nov.json")["evidence_routing"], True)

    def test_option_settings_live_in_their_own_files(self) -> None:
        for name in ("section_context.json", "form_blocks.json", "table_join.json"):
            self.assertTrue((ROOT / "configs" / "corpus" / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
