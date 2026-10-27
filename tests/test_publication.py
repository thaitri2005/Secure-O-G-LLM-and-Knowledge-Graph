"""Release publication: interruption at any step leaves a complete current release (E9 export-interruption probe)."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from graph_builder import publication
from graph_builder.publication import PublicationError, current_release, publish


def staged(base: Path, content: str) -> Path:
    directory = Path(tempfile.mkdtemp(dir=base))
    (directory / "data.txt").write_text(content, encoding="utf-8")
    (directory / "manifest.json").write_text("{}", encoding="utf-8")
    (directory / "SHA256SUMS").write_text(f"{content}\n", encoding="utf-8")
    return directory


class PublicationTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.base = Path(self.directory.name)
        self.root = self.base / "v1"

    def tearDown(self):
        self.directory.cleanup()

    def read(self) -> str:
        return (current_release(self.root) / "data.txt").read_text(encoding="utf-8")

    def test_publish_switches_and_keeps_the_previous_release(self):
        first = publish(staged(self.base, "one"), self.root, "manifest.json", "a" * 64)
        second = publish(staged(self.base, "two"), self.root, "manifest.json", "b" * 64)
        self.assertEqual(self.read(), "two")
        self.assertTrue(first.is_dir())  # a reader pinned to the old release can finish
        pointer = json.loads((self.root / "CURRENT.json").read_text(encoding="utf-8"))
        self.assertEqual((pointer["release"], pointer["previous"]), (second.name, first.name))
        publish(staged(self.base, "three"), self.root, "manifest.json", "c" * 64)
        self.assertFalse(first.exists())  # older than the previous release: pruned
        self.assertEqual(len(list((self.root / "releases").iterdir())), 2)

    def test_interrupted_pointer_switch_keeps_the_current_release(self):
        publish(staged(self.base, "one"), self.root, "manifest.json", "a" * 64)
        with mock.patch.object(publication.os, "replace", side_effect=OSError("power cut")):
            with self.assertRaises(OSError):
                publish(staged(self.base, "two"), self.root, "manifest.json", "b" * 64)
        self.assertEqual(self.read(), "one")

    def test_invalid_staging_is_never_published(self):
        publish(staged(self.base, "one"), self.root, "manifest.json", "a" * 64)
        with self.assertRaises(PublicationError):
            publish(staged(self.base, "bad"), self.root, "manifest.json", "b" * 64, validate=lambda path: ["broken"])
        self.assertEqual(self.read(), "one")

    def test_refuses_unrelated_directories_and_reads_old_flat_bundles(self):
        self.root.mkdir()
        (self.root / "notes.txt").write_text("mine", encoding="utf-8")
        with self.assertRaises(PublicationError):
            publish(staged(self.base, "one"), self.root, "manifest.json", "a" * 64)
        flat = self.base / "flat"
        flat.mkdir()
        (flat / "SHA256SUMS").write_text("", encoding="utf-8")
        self.assertEqual(current_release(flat), flat)


class ExportValidationTest(unittest.TestCase):
    def test_corpus_export_is_checked_against_its_sums_before_publication(self):
        from graph_builder.corpus.export import FILES, validate_export
        from graph_builder.corpus.store import file_sha256
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            for name in (*FILES, "manifest.json"):
                (directory / name).write_text(name, encoding="utf-8")
            (directory / "SHA256SUMS").write_text("".join(f"{file_sha256(directory / n)}  {n}\n"
                                                          for n in (*FILES, "manifest.json")), encoding="utf-8")
            self.assertEqual(validate_export(directory), [])
            (directory / "chunks.jsonl").write_text("changed", encoding="utf-8")
            self.assertEqual(validate_export(directory), ["chunks.jsonl: SHA256 differs"])


if __name__ == "__main__":
    unittest.main()
