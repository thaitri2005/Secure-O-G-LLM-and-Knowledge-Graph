"""A-443: scripts/evaluate_ops_tables.py reads both freeze layouts and reports an unusable freeze file clearly.

Root cause of the B3 failure (``KeyError: 'sources_sha256'`` with ``--split all``): the harness read only the key
``sources_sha256`` (written by ``--write-freeze``), while the Round 2 code freeze (``freeze.json``) stores its hashes under
``files_sha256``. No PDF is opened here; scratch files go under data/interim/overnight/b4/ (git-ignored) and are removed.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ROUND_TWO_FREEZE = ROOT / "data/interim/ops-rebuild-r2/freeze.json"


def load_harness():
    spec = importlib.util.spec_from_file_location("evaluate_ops_tables_a443", ROOT / "scripts/evaluate_ops_tables.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FreezeLayoutTests(unittest.TestCase):

    def setUp(self):
        self.harness = load_harness()
        self.scratch = ROOT / "data/interim/overnight/b4/_test_a443_freeze"
        shutil.rmtree(self.scratch, ignore_errors=True)
        (self.scratch / "release").mkdir(parents=True)
        (self.scratch / "release/SHA256SUMS").write_text("abc  manifest.json\n", encoding="utf-8")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.harness.LOCK = self.scratch / "lock.json"
        self.harness.FREEZE = self.scratch / "freeze.json"

    def write_freeze(self, payload, raw=None):
        self.harness.FREEZE.write_text(raw if raw is not None else json.dumps(payload), encoding="utf-8")

    def lock_entry(self):
        return json.loads(self.harness.LOCK.read_text(encoding="utf-8"))["rounds"][0]

    def test_the_round_two_layout_files_sha256_is_accepted_and_only_its_files_are_compared(self):
        digests = self.harness.source_digests()
        same = "src/graph_builder/corpus/ops_tables.py"
        changed = "scripts/evaluate_ops_tables.py"
        self.write_freeze({"files_sha256": {same: digests[same], changed: "0" * 64}})
        self.harness.take_lock(self.scratch / "release", new_round=False)
        entry = self.lock_entry()
        self.assertEqual(entry["changed_since_dev_freeze"], [changed])  # the many other source files are not in the freeze
        self.assertEqual(entry["freeze_key"], "files_sha256")
        self.assertIn("only the 2 files", entry["freeze_scope"])

    def test_a_file_listed_in_the_freeze_but_gone_counts_as_changed(self):
        self.write_freeze({"files_sha256": {"src/graph_builder/corpus/no_such_module.py": "1" * 64}})
        self.harness.take_lock(self.scratch / "release", new_round=False)
        self.assertEqual(self.lock_entry()["changed_since_dev_freeze"], ["src/graph_builder/corpus/no_such_module.py"])

    def test_the_sources_layout_still_compares_the_union(self):
        self.harness.write_freeze()
        frozen = json.loads(self.harness.FREEZE.read_text(encoding="utf-8"))
        del frozen["sources_sha256"]["src/graph_builder/corpus/ops_tables.py"]  # in the tree, not in the freeze
        self.write_freeze(frozen)
        self.harness.take_lock(self.scratch / "release", new_round=False)
        entry = self.lock_entry()
        self.assertEqual(entry["changed_since_dev_freeze"], ["src/graph_builder/corpus/ops_tables.py"])
        self.assertEqual(entry["freeze_key"], "sources_sha256")
        self.assertNotIn("freeze_scope", entry)

    def test_an_unknown_layout_is_a_clear_error_not_a_key_error(self):
        for payload, expected in (({"hashes": {}}, "found: \\['hashes'\\]"), ([1, 2], "found: list"),
                                  ({"files_sha256": ["a"]}, "must map file names"),
                                  ({"sources_sha256": {"a": 1}}, "must map file names")):
            with self.subTest(payload=payload):
                self.write_freeze(payload)
                with self.assertRaisesRegex(SystemExit, expected):
                    self.harness.load_freeze(self.harness.FREEZE)
        self.write_freeze(None, raw="{not json")
        with self.assertRaisesRegex(SystemExit, "not readable JSON"):
            self.harness.load_freeze(self.harness.FREEZE)
        self.harness.FREEZE.write_bytes(b'{"files_sha256": {"a": "\x9d"}}')  # bytes that are not UTF-8
        with self.assertRaisesRegex(SystemExit, "not readable JSON"):
            self.harness.load_freeze(self.harness.FREEZE)
        with self.assertRaisesRegex(SystemExit, "not found"):
            self.harness.load_freeze(self.scratch / "missing.json")

    def test_a_utf8_bom_in_the_freeze_file_is_read(self):
        self.harness.FREEZE.write_bytes(b"\xef\xbb\xbf" + json.dumps({"files_sha256": {"a.py": "2" * 64}}).encode("utf-8"))
        self.assertEqual(self.harness.load_freeze(self.harness.FREEZE), ({"a.py": "2" * 64}, "files_sha256"))

    def test_an_unusable_freeze_stops_the_run_before_any_pdf_is_read_and_leaves_no_lock_or_results(self):
        files = [{"file_id": f"f{n}", "doc_id": f"gdr-appx-{n}-x", "original_name": f"appx_{n}.pdf"} for n in (27, 28, 30)]
        release, raw = self.scratch / "release", self.scratch / "raw"
        raw.mkdir()
        (release / "files.jsonl").write_text("".join(json.dumps(f) + "\n" for f in files), encoding="utf-8")
        (release / "tables.jsonl").write_text("", encoding="utf-8")
        results = self.scratch / "results.json"
        args = ["--release", f"after={release}", "--split", "all", "--final", "--new-round", "--raw", str(raw),
                "--lock", str(self.harness.LOCK), "--freeze", str(self.harness.FREEZE), "--out", str(results)]
        with patch.dict("sys.modules", {"fitz": types.ModuleType("fitz")}), \
                patch.object(self.harness, "scan_pdfs", side_effect=AssertionError("PDFs must not be read")):
            self.write_freeze({"stage": "D"})
            # --new-round needs an earlier lock: a seed lock is given so only the freeze can fail
            seed = self.scratch / "seed.json"
            seed.write_text(json.dumps({"rounds": []}), encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "has none of the keys"):
                self.harness.main(args + ["--seed-lock", str(seed)])
            self.assertFalse(self.harness.LOCK.exists())  # not even the seed copy
            self.assertFalse(results.exists())

    def test_a_missing_freeze_file_keeps_the_old_behaviour_and_is_recorded_in_the_lock(self):
        self.harness.take_lock(self.scratch / "release", new_round=False)
        self.assertIn("no dev-freeze.json", self.lock_entry()["changed_since_dev_freeze"])

    @unittest.skipUnless(ROUND_TWO_FREEZE.is_file(), "Round 2 freeze.json is not on this machine")

    def test_the_real_round_two_freeze_file_loads(self):
        hashes, key = self.harness.load_freeze(ROUND_TWO_FREEZE)
        self.assertEqual(key, "files_sha256")
        self.assertEqual(len(hashes), 15)


if __name__ == "__main__":
    unittest.main()
