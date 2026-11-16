"""C-04: the optional ``cache.code_version`` key adds the processing source to the fingerprint; off, nothing changes."""
from __future__ import annotations

import copy
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from graph_builder.corpus import config as config_module
from graph_builder.corpus.config import KEYS, code_digest, fingerprint, load_config, validate_config

ROOT = Path(__file__).resolve().parents[1]


def default() -> dict:
    return load_config(ROOT / "configs/corpus/default.json")


def with_cache(value) -> dict:
    return validate_config(dict(copy.deepcopy(default()), cache=value))


def fingerprint_before_c04(config: dict, ocr_models: dict) -> str:
    """The fingerprint formula as it was before this option existed."""
    material = {"pipeline": config_module.PIPELINE_VERSION, "docling": version("docling"),
                "docling-core": version("docling-core"),
                "settings": {key: config[key] for key in sorted(KEYS - {"allowed_hosts", "limits"})},
                "ocr_models": ocr_models}
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()[:16]


class FingerprintOptionTests(unittest.TestCase):
    def test_off_is_the_fingerprint_of_before(self):
        for models in ({}, {"detect": "abc"}):
            self.assertEqual(fingerprint(default(), models), fingerprint_before_c04(default(), models))

    def test_the_shared_default_has_no_cache_key(self):
        raw = json.loads((ROOT / "configs/corpus/default.json").read_text(encoding="utf-8-sig"))
        self.assertNotIn("cache", raw)
        self.assertNotIn("cache", default())

    def test_an_explicit_false_equals_absent(self):
        self.assertEqual(fingerprint(with_cache({"code_version": False}), {}), fingerprint(default(), {}))

    def test_on_differs_from_off_and_follows_the_code(self):
        on = with_cache({"code_version": True})
        with patch.object(config_module, "code_digest", return_value="a" * 64):
            first = fingerprint(on, {})
            self.assertEqual(first, fingerprint(on, {}))
        with patch.object(config_module, "code_digest", return_value="b" * 64):
            second = fingerprint(on, {})
        self.assertNotEqual(first, second)
        self.assertNotIn(first, (fingerprint(default(), {}), second))

    def test_on_is_deterministic_for_the_real_source(self):
        on = with_cache({"code_version": True})
        self.assertEqual(fingerprint(on, {}), fingerprint(on, {}))
        self.assertRegex(code_digest(), r"^[0-9a-f]{64}$")

    def test_the_other_settings_still_change_the_fingerprint(self):
        on = with_cache({"code_version": True})
        other = copy.deepcopy(on)
        other["segment_pages"] = on["segment_pages"] + 1
        self.assertNotEqual(fingerprint(on, {}), fingerprint(other, {}))

    def test_invalid_cache_values_are_rejected(self):
        for bad in ({}, {"code_version": "yes"}, {"code_version": 1}, {"code_version": True, "x": 1}, True, None, []):
            with self.assertRaises(ValueError, msg=repr(bad)):
                with_cache(bad)

    def test_other_unknown_top_level_keys_are_still_rejected(self):
        with self.assertRaises(ValueError):
            validate_config(dict(copy.deepcopy(default()), surprise=1))
        broken = copy.deepcopy(default())
        del broken["quality"]
        with self.assertRaises(ValueError):
            validate_config(broken)


class RunningLineSemanticsTests(unittest.TestCase):
    def with_tolerance(self, value=0.01):
        config = default()
        config["filters"]["running_line_position_tolerance"] = value
        return validate_config(config)

    def test_absent_key_keeps_the_old_fingerprint(self):
        for models in ({}, {"detect": "abc"}):
            self.assertEqual(fingerprint(default(), models), fingerprint_before_c04(default(), models))

    def test_present_key_invalidates_global_tolerance_work(self):
        config = self.with_tolerance()
        self.assertNotEqual(fingerprint(config, {}), fingerprint_before_c04(config, {}))
        self.assertEqual(fingerprint(config, {}), fingerprint(config, {}))
        self.assertNotEqual(fingerprint(config, {}), fingerprint(self.with_tolerance(0.02), {}))

    def test_semantics_marker_also_applies_with_code_version(self):
        config = self.with_tolerance()
        config["cache"] = {"code_version": True}
        with patch.object(config_module, "code_digest", return_value="a" * 64):
            material = {"pipeline": config_module.PIPELINE_VERSION, "docling": version("docling"),
                        "docling-core": version("docling-core"),
                        "settings": {key: config[key] for key in sorted(KEYS - {"allowed_hosts", "limits"})},
                        "ocr_models": {}, "code": "a" * 64}
            old = hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()[:16]
            self.assertNotEqual(fingerprint(config, {}), old)

    def test_old_completed_directory_does_not_skip_new_work(self):
        from graph_builder.corpus.catalog import Corpus
        from graph_builder.corpus.process import document_state, output_directory
        config = self.with_tolerance()
        with tempfile.TemporaryDirectory() as temporary:
            corpus = Corpus.create(Path(temporary), config)
            old_dir = output_directory(corpus, "test-doc", fingerprint_before_c04(config, {}))
            old_dir.mkdir(parents=True)
            content = b"old global tolerance output"
            (old_dir / "text.txt").write_bytes(content)
            (old_dir / "manifest.json").write_text(json.dumps({"files": {"text.txt": hashlib.sha256(content).hexdigest()}}))
            self.assertEqual(document_state(old_dir, None)[0], "completed")
            new_dir = output_directory(corpus, "test-doc", fingerprint(config, {}))
            self.assertNotEqual(old_dir, new_dir)
            self.assertEqual(document_state(new_dir, None)[0], "not_started")
            self.assertEqual((old_dir / "text.txt").read_bytes(), content)


class CodeDigestTests(unittest.TestCase):
    def tree(self, files: dict[str, bytes]) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for name, content in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_bytes(content)
        return root

    BASE = {"corpus/chunking.py": b"a = 1\n", "ingestion/filters.py": b"b = 2\n", "corpus/qa/ledger.py": b"q = 0\n",
            "corpus/k1_build.py": b"k = 0\n", "corpus/export.py": b"e = 0\n", "corpus/__main__.py": b"m = 0\n"}

    def test_processing_files_change_the_digest(self):
        base = code_digest(self.tree(self.BASE))
        for name in ("corpus/chunking.py", "ingestion/filters.py"):
            changed = code_digest(self.tree(dict(self.BASE, **{name: b"changed = True\n"})))
            self.assertNotEqual(base, changed, name)
        self.assertNotEqual(base, code_digest(self.tree(dict(self.BASE, **{"corpus/new_stage.py": b"x = 1\n"}))))

    def test_downstream_files_do_not(self):
        base = code_digest(self.tree(self.BASE))
        for name in ("corpus/qa/ledger.py", "corpus/k1_build.py", "corpus/export.py", "corpus/__main__.py"):
            self.assertEqual(base, code_digest(self.tree(dict(self.BASE, **{name: b"changed = True\n"}))), name)

    def test_line_endings_and_non_python_files_do_not(self):
        base = code_digest(self.tree(self.BASE))
        crlf = {name: content.replace(b"\n", b"\r\n") for name, content in self.BASE.items()}
        self.assertEqual(base, code_digest(self.tree(crlf)))
        self.assertEqual(base, code_digest(self.tree(dict(self.BASE, **{"corpus/notes.txt": b"x", "corpus/__pycache__/a.pyc": b"x"}))))

    def test_a_renamed_file_changes_the_digest(self):
        renamed = {("corpus/chunking2.py" if name == "corpus/chunking.py" else name): content
                   for name, content in self.BASE.items()}
        self.assertNotEqual(code_digest(self.tree(self.BASE)), code_digest(self.tree(renamed)))


if __name__ == "__main__":
    unittest.main()
