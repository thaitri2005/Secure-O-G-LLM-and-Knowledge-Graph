"""platform/render_pages.py: one PNG per page with pypdfium2, skipping what exists, in the layout the backend serves."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

try:
    import pypdfium2 as pdfium
except ImportError:
    pdfium = None

SPEC = importlib.util.spec_from_file_location("render_pages", Path(__file__).resolve().parents[1] / "platform/render_pages.py")
render_pages = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render_pages)


def make_pdf(path: Path, pages: int) -> None:
    document = pdfium.PdfDocument.new()
    for _ in range(pages):
        document.new_page(200, 300)
    document.save(str(path))


@unittest.skipIf(pdfium is None, "needs pypdfium2")
class RenderPagesTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.pdf = self.root / "report.pdf"
        make_pdf(self.pdf, 3)
        self.out = self.root / "pages"

    def test_one_png_per_page_numbered_from_one_at_150_dpi(self):
        self.assertEqual(render_pages.render_pdf(self.pdf, "report1", self.out), (3, 0))
        names = sorted(p.name for p in (self.out / "report1").iterdir())
        self.assertEqual(names, ["p1.png", "p2.png", "p3.png"])
        from PIL import Image
        with Image.open(self.out / "report1" / "p1.png") as image:
            self.assertEqual((image.format, image.size), ("PNG", (round(200 * 150 / 72), round(300 * 150 / 72))))

    def test_pages_already_rendered_are_skipped_and_left_untouched(self):
        render_pages.render_pdf(self.pdf, "report1", self.out)
        kept = self.out / "report1" / "p2.png"
        before = kept.stat().st_mtime_ns
        (self.out / "report1" / "p3.png").unlink()
        self.assertEqual(render_pages.render_pdf(self.pdf, "report1", self.out), (1, 2))
        self.assertEqual(kept.stat().st_mtime_ns, before)

    def test_a_file_id_that_is_not_a_plain_name_is_refused(self):
        for bad in ("../x", "a/b", "", ".hidden", "a b"):
            with self.assertRaises(ValueError, msg=bad):
                render_pages.render_pdf(self.pdf, bad, self.out)

    def test_a_release_is_rendered_by_its_file_records_and_checks_the_digest(self):
        release, sources = self.root / "release", self.root / "sources"
        release.mkdir()
        (sources / "sub").mkdir(parents=True)
        sub = sources / "sub" / "report.pdf"
        sub.write_bytes(self.pdf.read_bytes())
        records = [
            {"file_id": "f1", "original_name": "report.pdf", "sha256": render_pages.sha256(sub), "page_count": 3},
            {"file_id": "f2", "original_name": "report.pdf", "sha256": "0" * 64, "page_count": 3},
            {"file_id": "f3", "original_name": "missing.pdf", "sha256": "0" * 64, "page_count": 1},
        ]
        (release / "files.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
        results = {r["file_id"]: r["status"] for r in render_pages.render_release(release, sources, self.out)}
        self.assertEqual(results, {"f1": "ok", "f2": "sha256 differs from the release", "f3": "pdf not found"})
        self.assertEqual(len(list((self.out / "f1").glob("p*.png"))), 3)
        self.assertFalse((self.out / "f2").exists())

    def test_the_command_line_renders_one_file(self):
        code = render_pages.main([str(self.pdf), "--file-id", "report1", "--out", str(self.out)])
        self.assertEqual(code, 0)
        self.assertTrue((self.out / "report1" / "p3.png").is_file())


if __name__ == "__main__":
    unittest.main()
