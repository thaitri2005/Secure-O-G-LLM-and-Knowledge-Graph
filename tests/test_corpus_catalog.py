import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from graph_builder.corpus.catalog import Corpus, slug
from graph_builder.corpus.config import load_config, validate_config
from graph_builder.corpus.formats import UnsupportedFormat, detect_format

ROOT = Path(__file__).resolve().parents[1]


class CorpusCatalogTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.base = Path(self.directory.name)
        self.corpus = Corpus.create(self.base / "corpus", load_config(ROOT / "configs/corpus/default.json"))

    def tearDown(self):
        self.directory.cleanup()

    def write(self, name, content):
        path = self.base / name
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return path

    def test_add_deduplicates_by_content_and_rejects_unsupported(self):
        note = self.write("Ghi chú Đầu tiên.md", "# Tiêu đề\n\nNội dung.\n")
        status, doc_id = self.corpus.add_file(note)
        self.assertEqual(status, "added")
        self.assertTrue(doc_id.startswith("ghi-chu-dau-tien-"))
        copy = self.write("copy.md", "# Tiêu đề\n\nNội dung.\n")
        self.assertEqual(self.corpus.add_file(copy), ("duplicate", doc_id))
        legacy = self.write("old.doc", b"\xd0\xcf\x11\xe0" + b"\0" * 100)
        status, reason = self.corpus.add_file(legacy)
        self.assertEqual(status, "rejected")
        self.assertIn("legacy Office", reason)
        stored = self.corpus.blob(self.corpus.documents()[0]["sha256"])
        self.assertEqual(stored.read_bytes(), note.read_bytes())

    def test_size_limit(self):
        config = json.loads((self.corpus.root / "config.json").read_text(encoding="utf-8"))
        config["limits"]["max_bytes"] = 10
        (self.corpus.root / "config.json").write_text(json.dumps(config), encoding="utf-8")
        status, reason = self.corpus.add_file(self.write("big.md", "x" * 100))
        self.assertEqual(status, "rejected")
        self.assertIn("outside", reason)

    def test_detect_formats(self):
        self.assertEqual(detect_format(self.write("a.pdf", b"%PDF-1.7\n")), "pdf")
        self.assertEqual(detect_format(self.write("a.txt", "chữ")), "text")
        archive = self.base / "a.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("x.csv", "a,b")
        with self.assertRaises(UnsupportedFormat):
            detect_format(archive)
        with self.assertRaises(UnsupportedFormat):
            detect_format(self.write("a.txt2", "?"))

    def test_slug_and_config_validation(self):
        self.assertEqual(slug("Luật Dầu khí 2022"), "luat-dau-khi-2022")
        config = load_config(ROOT / "configs/corpus/default.json")
        config["ocr"]["engine"] = "unknown"
        with self.assertRaises(ValueError):
            validate_config(config)


if __name__ == "__main__":
    unittest.main()
