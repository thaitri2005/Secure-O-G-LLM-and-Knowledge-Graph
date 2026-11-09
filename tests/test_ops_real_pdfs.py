"""The Operations Summary rule on the real daily-report PDFs of data/raw: equivalence with Round 1, and invariance.

These pages are DEVELOPMENT data (they were used to design and tune the rule), so every result here is a regression
check on data already seen, not an independent evaluation. The tests are skipped when ``data/raw`` or the Round 1 code
snapshot is missing (another machine). No document id, page number or table count is written in the code of the rule:
the pages are found by their text, and the expected differences by their structure (a title with an annotation).
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
from pathlib import Path
import random
import unittest

from graph_builder.corpus import ops_tables as ops
from graph_builder.corpus import table_recognition as recognition
from ops_fixtures import OPS_RULE

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / ".track-a-private/evidence/A-107-ops-tables/round1-code-snapshot/src/graph_builder/corpus/ops_tables.py"
RAW = ROOT / "data/raw"
SEED = 20261108  # the jitter is seeded, so the check is reproducible


def load_round_one():
    spec = importlib.util.spec_from_file_location("graph_builder.corpus.ops_tables_r1", SNAPSHOT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def unique_daily_reports() -> list[Path]:
    """Daily-report PDFs of data/raw, one file per distinct content (the appendices are also bundled twice)."""
    seen, found = set(), []
    for path in sorted(RAW.glob("*dailyreport*.pdf")):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest not in seen:
            seen.add(digest)
            found.append(path)
    return found


def transform(layer: dict, scale: float = 1.0, dx: float = 0.0, dy: float = 0.0, jitter: random.Random | None = None,
              em: float = 0.0) -> dict:
    """The same page printed at another size or position; with ``jitter`` every word (and its glyphs, by the same
    amount) moves by a random x of at most 0.1 em and a random y of at most 0.005 em, em being the header text height."""
    result = copy.deepcopy(layer)
    deltas: dict[int, tuple[float, float]] = {}

    def move(box, shift=(0.0, 0.0)):
        return [box[0] * scale + dx + shift[0], box[1] * scale + dy + shift[1],
                box[2] * scale + dx + shift[0], box[3] * scale + dy + shift[1]]

    for index, word in enumerate(result["words"]):
        shift = (jitter.uniform(-0.1, 0.1) * em, jitter.uniform(-0.005, 0.005) * em) if jitter else (0.0, 0.0)
        deltas[index] = shift
        word["bbox"] = move(word["bbox"], shift)
    # glyphs follow the word they belong to: match them by position in the original layer
    boxes = [(index, word["bbox"]) for index, word in enumerate(layer["words"])]
    for char in result["chars"]:
        owner = next((i for i, box in boxes if box[0] - 0.01 <= char["bbox"][0] and char["bbox"][2] <= box[2] + 0.01
                      and box[1] - 0.01 <= char["bbox"][1] and char["bbox"][3] <= box[3] + 0.01), None)
        char["bbox"] = move(char["bbox"], deltas.get(owner, (0.0, 0.0)))
    result["width"], result["height"] = layer["width"] * scale, layer["height"] * scale
    return result


class RealDailyReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not RAW.is_dir() or not SNAPSHOT.is_file():
            raise unittest.SkipTest("data/raw or the Round 1 code snapshot is not available")
        import pypdfium2
        from graph_builder.corpus.report_context import pdf_page_texts
        from graph_builder.corpus.text_layer import source_page
        cls.round_one = load_round_one()
        gate = recognition.title_phrase_pattern(OPS_RULE)
        cls.pages = []  # (file name, page, text layer) of every page that holds a title
        for pdf in unique_daily_reports():
            with pypdfium2.PdfDocument(pdf) as document:
                numbers = list(range(1, len(document) + 1))
            texts = pdf_page_texts(pdf, numbers)
            for page in numbers:
                if __import__("re").search(gate, texts[page]):
                    layer = source_page(pdf, page)
                    if recognition.mention_lines(layer, OPS_RULE):
                        cls.pages.append((pdf.name, page, layer))
        if not cls.pages:
            raise unittest.SkipTest("no daily-report page with the title in data/raw")

    def test_the_pages_were_found(self):
        self.assertGreater(len(self.pages), 0)

    def test_column_zones_are_exactly_those_of_round_one(self):
        checked = 0
        for name, page, layer in self.pages:
            lines = recognition.page_lines(layer)
            for mention in recognition.mention_lines(layer, OPS_RULE, lines):
                if not mention["passed"]:
                    continue
                header = recognition.recognise_header(lines, mention["line"], OPS_RULE)
                if not header["ok"]:
                    continue
                with self.subTest(file=name, page=page):
                    self.assertEqual(recognition.zones_from_header(header["boxes"], OPS_RULE),
                                     self.round_one.header_zones(lines[header["line"]]))
                checked += 1
        self.assertGreater(checked, 0)

    def test_every_page_gives_the_same_table_as_round_one_or_a_title_with_an_annotation(self):
        same, extra = 0, []
        for name, page, layer in self.pages:
            old, new = self.round_one.read_page(layer), ops.read_page(layer, OPS_RULE)
            key = lambda results: [(r["status"], r.get("rows"), r.get("bbox"), r.get("span"), r["index"]) for r in results]  # noqa: E731
            if key(old) == key(new):
                same += 1
                continue
            with self.subTest(file=name, page=page):
                # the only intended difference: Round 1 found no title because of the annotation on the title line
                self.assertEqual(old, [])
                self.assertTrue(new and all(r["annotations"] for r in new))
                self.assertTrue(all(r["status"] == "rebuilt" for r in new))
            extra.append((name, page))
        self.assertGreater(same, 0)
        # recorded for the report: regression on data already seen, not an independent result
        self.assertEqual(len(extra), sum(1 for _, _, layer in self.pages if any(
            m["passed"] and m["annotations"] for m in recognition.mention_lines(layer, OPS_RULE))))

    def test_removing_the_annotation_words_gives_the_table_of_the_original_code(self):
        for name, page, layer in self.pages:
            [mention] = [m for m in recognition.mention_lines(layer, OPS_RULE) if m["passed"]] or [None]
            if mention is None or not mention["annotations"]:
                continue
            lines = recognition.page_lines(layer)
            title = lines[mention["line"]]["words"]
            keep = {id(w) for w in title if w["text"] in OPS_RULE["schema"]["title_words"]}
            stripped = copy.deepcopy(layer)
            drop = {(w["text"], tuple(w["bbox"])) for w in title if id(w) not in keep}
            stripped["words"] = [w for w in stripped["words"] if (w["text"], tuple(w["bbox"])) not in drop]
            [after] = ops.read_page(layer, OPS_RULE)
            [before] = self.round_one.read_page(stripped)
            with self.subTest(file=name, page=page):
                self.assertEqual((before["status"], before["rows"], before["bbox"]), (after["status"], after["rows"], after["bbox"]))

    def assert_same_tables(self, make, label):
        for name, page, layer in self.pages:
            expected = ops.read_page(layer, OPS_RULE)
            em = recognition.em(recognition.page_lines(layer)[0]["words"])
            actual = ops.read_page(make(layer, em), OPS_RULE)
            with self.subTest(case=label, file=name, page=page):
                self.assertEqual([(r["status"], r["reason"], r["index"], r.get("rows")) for r in actual],
                                 [(r["status"], r["reason"], r["index"], r.get("rows")) for r in expected])

    def test_a_smaller_or_larger_page_gives_the_same_tables(self):
        for scale in (0.75, 1.5):
            self.assert_same_tables(lambda layer, em, scale=scale: transform(layer, scale=scale), f"scale {scale}")

    def test_moving_the_page_content_vertically_gives_the_same_tables(self):
        for dy in (-40.0, 40.0):
            self.assert_same_tables(lambda layer, em, dy=dy: transform(layer, dy=dy), f"y shift {dy}")

    def test_small_seeded_jitter_gives_the_same_tables(self):
        # x within 0.1 em and y within 0.005 em per word, chosen before the run; the seed is fixed.
        jitter = random.Random(SEED)
        for name, page, layer in self.pages:
            header_lines = [line for line in recognition.page_lines(layer) if len(line["words"]) > 5]
            em = recognition.em(header_lines[0]["words"]) if header_lines else 9.0
            expected = ops.read_page(layer, OPS_RULE)
            actual = ops.read_page(transform(layer, jitter=jitter, em=em), OPS_RULE)
            with self.subTest(file=name, page=page):
                self.assertEqual([(r["status"], r["reason"], r["index"], r.get("rows")) for r in actual],
                                 [(r["status"], r["reason"], r["index"], r.get("rows")) for r in expected])

    def test_a_sentence_naming_the_table_does_not_disturb_a_real_table(self):
        for name, page, layer in self.pages:
            changed = copy.deepcopy(layer)
            row = max(w["row"] for w in changed["words"]) + 1
            x = 40.0
            for text in ("See", "Operations", "Summary", "below"):
                changed["words"].append({"text": text, "bbox": [x, 5.0, x + 6.0 * len(text), 14.0], "row": row})
                changed["chars"] += [{"text": c, "bbox": [x + 6.0 * i, 5.0, x + 6.0 * (i + 1), 14.0], "index": 10 ** 6 + i}
                                     for i, c in enumerate(text)]
                x += 6.0 * len(text) + 2.0
            expected = ops.read_page(layer, OPS_RULE)
            actual = ops.read_page(changed, OPS_RULE)
            with self.subTest(file=name, page=page):
                self.assertEqual([(r["status"], r.get("rows")) for r in actual], [(r["status"], r.get("rows")) for r in expected])
                self.assertEqual([m["detail"] for m in ops.page_rejections(changed, OPS_RULE)], ["embedded_in_text"])

    def test_a_damaged_header_is_not_rebuilt_and_is_reported_as_unsupported(self):
        for name, page, layer in self.pages:
            changed = copy.deepcopy(layer)
            label = next(w for w in changed["words"] if w["text"] == "Elapsed")
            label["text"] = "Elapsd"
            for result in ops.read_page(changed, OPS_RULE):
                with self.subTest(file=name, page=page):
                    self.assertEqual((result["status"], result["reason"], ops.state_of(result["reason"])),
                                     ("fallback", "header_labels_missing", "UNSUPPORTED_FORMAT"))


if __name__ == "__main__":
    unittest.main()
