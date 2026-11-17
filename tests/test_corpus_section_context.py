"""A-434: optional K1 section clean-up (page banners, date stamps, e-mail headings) and numbered heading hierarchy."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from graph_builder.corpus.k1_build import map_children
from graph_builder.corpus.k1_config import load_k1_config, validate_k1_config
from graph_builder.corpus.k1_export import package_identity
from graph_builder.corpus.section_context import (
    band_boxes, band_lines, classify_sections, clean_path, compile_numbering, furniture_values, hierarchy_path,
    is_banner, non_section_values, normalise, validate_section_context)
from test_corpus_k1 import FID, K1_CONFIG, PackageCase, add_sample, corpus_chunk

ROOT = Path(__file__).resolve().parents[1]
OPTIONS = json.loads((ROOT / "configs/corpus/section_context.json").read_text(encoding="utf-8"))
FURNITURE = OPTIONS["furniture"]
PATTERNS = OPTIONS["value_patterns"]
NUMBERING = compile_numbering(OPTIONS["numbered_hierarchy"])


def text_pdf(path: Path, pages: list[list[tuple[int, int, str]]], rotate: int = 0, width: int = 600, height: int = 800) -> Path:
    """A minimal PDF whose pages hold the given (x, y from the bottom, text) lines in Helvetica 12."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for lines in pages:
        content = "".join(f"BT /F1 12 Tf {x} {y} Td ({text}) Tj ET\n" for x, y, text in lines).encode("latin-1")
        objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"endstream")
        number = len(objects)
        objects.append((f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] /Rotate {rotate} "
                        f"/Resources << /Font << /F1 3 0 R >> >> /Contents {number} 0 R >>").encode("latin-1"))
        kids.append(f"{len(objects)} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>".encode("latin-1")
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for index, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    start = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))
    return path


def report_pages(count: int, banner: str = "Weekly Drilling Report", heading: str = "Mud Information") -> list:
    """`count` pages with a banner (same place, a changing number) in the top band and a heading low on the page."""
    return [[(50, 770, banner), (350, 770, f"Page {n}"), (50, 400, heading if n == 2 else f"Topic {n}"), (50, 380, "Body text.")]
            for n in range(1, count + 1)]


class NormalisationTests(unittest.TestCase):
    def test_words_and_number_masking(self):
        self.assertEqual(normalise("Daily Drilling Report Well ID: AK-3"), "daily drilling report well id ak 3")
        self.assertEqual(normalise("Summary 21 Aug 16", mask_numbers=True), "summary # aug #")


class BannerTests(unittest.TestCase):
    BANNER = {("daily well graphical summary # aug # geothermal resource group", "well id ak # well name ak #"),
              ("end of well report and lessons learned well # # # march # #", "#")}

    def test_multi_line_banner_heading_is_recognised_in_docling_order(self):
        self.assertTrue(is_banner("Daily Well Graphical Summary Well ID: AK-3", self.BANNER))
        self.assertTrue(is_banner("Daily Well Graphical Summary", self.BANNER))

    def test_slice_of_a_banner_line_and_lone_words_and_numbers_are_not_banners(self):
        self.assertFalse(is_banner("Lessons Learned", self.BANNER))  # middle of a banner line: a real sub-heading
        self.assertFalse(is_banner("Well", self.BANNER))
        self.assertFalse(is_banner("3", self.BANNER))
        self.assertFalse(is_banner("Mud Information", self.BANNER))

    def test_value_patterns_flag_dates_and_emails_only(self):
        found = classify_sections(["Report For 12-Aug-16", "18-Aug-16", "2019-03-04", "name@example.org", "Cementing Report",
                                   "Results of 12-Aug-16 core analysis", "Operation Summary:", "Well Summary"], set(), PATTERNS)
        self.assertEqual(found, {"Report For 12-Aug-16": "report_date", "18-Aug-16": "report_date", "2019-03-04": "report_date",
                                 "name@example.org": "email"})

    def test_band_boxes_follow_the_display_rotation(self):
        top = {0: (0, 720, 600, 800), 90: (0, 0, 60, 800), 180: (0, 0, 600, 80), 270: (540, 0, 600, 800)}
        for rotation, expected in top.items():
            self.assertEqual(band_boxes(600, 800, rotation, 0.1, 0.1)["header"], tuple(float(v) for v in expected), rotation)


class TextLayerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def decide(self, pdf, sections):
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(pdf) as document:
            count = len(document)
        return non_section_values(pdf, list(range(1, count + 1)), sections, OPTIONS)

    def test_repeated_banner_is_dropped_and_the_real_heading_is_kept(self):
        pdf = text_pdf(self.root / "report.pdf", report_pages(8))
        found = self.decide(pdf, ["Weekly Drilling Report", "Mud Information", "Topic 3"])
        self.assertEqual(found, {"Weekly Drilling Report": "banner"})

    def test_banner_in_a_short_document_is_not_recognised(self):
        pdf = text_pdf(self.root / "short.pdf", report_pages(2))
        self.assertEqual(self.decide(pdf, ["Weekly Drilling Report"]), {})

    def test_a_heading_outside_the_header_band_is_never_a_banner(self):
        pages = [[(50, 400, "Repeated Heading"), (50, 380, "Body.")] for _ in range(8)]
        self.assertEqual(self.decide(text_pdf(self.root / "mid.pdf", pages), ["Repeated Heading"]), {})

    def test_rotated_pages_give_no_banner_evidence(self):
        pdf = text_pdf(self.root / "rotated.pdf", report_pages(8), rotate=90)
        self.assertEqual(self.decide(pdf, ["Weekly Drilling Report"]), {})

    def test_banner_with_a_changing_number_is_recognised(self):
        pages = [[(50, 770, f"Daily Summary {n} Aug 16"), (50, 400, "Plan")] for n in range(1, 9)]
        self.assertEqual(self.decide(text_pdf(self.root / "numbered.pdf", pages), ["Daily Summary"]), {"Daily Summary": "banner"})

    def test_unreadable_pages_are_skipped_not_fatal(self):
        pdf = text_pdf(self.root / "report.pdf", report_pages(4))
        self.assertEqual(set(band_lines(pdf, [1, 99], FURNITURE)), {1})
        self.assertEqual(furniture_values({}, FURNITURE), set())

    def test_result_is_deterministic(self):
        pdf = text_pdf(self.root / "report.pdf", report_pages(8))
        sections = ["Weekly Drilling Report", "Mud Information", "Report For 12-Aug-16"]
        self.assertEqual(self.decide(pdf, sections), self.decide(pdf, list(reversed(sections))))


class HierarchyTests(unittest.TestCase):
    def test_numbered_children_get_their_numbered_parents(self):
        seen = {}
        self.assertEqual(hierarchy_path("VI. Drilling Operations", seen, NUMBERING), ["VI. Drilling Operations"])
        self.assertEqual(hierarchy_path("VI.1 Drilling BHA 18", seen, NUMBERING), ["VI. Drilling Operations", "VI.1 Drilling BHA 18"])
        self.assertEqual(hierarchy_path("6. Results", seen, NUMBERING), ["6. Results"])
        self.assertEqual(hierarchy_path("6.2.4. Casing", seen, NUMBERING), ["6. Results", "6.2.4. Casing"])  # 6.2 never seen: not invented

    def test_no_evidence_keeps_the_flat_path(self):
        seen = {}
        self.assertEqual(hierarchy_path("V.12 Recommendations", seen, NUMBERING), ["V.12 Recommendations"])
        self.assertEqual(hierarchy_path("Lessons Learned", seen, NUMBERING), ["Lessons Learned"])
        self.assertEqual(hierarchy_path("Table 3 Costs", seen, NUMBERING), ["Table 3 Costs"])

    def test_roman_and_decimal_schemes_do_not_mix(self):
        seen = {}
        hierarchy_path("1. Introduction", seen, NUMBERING)
        self.assertEqual(hierarchy_path("I.1 Scope", seen, NUMBERING), ["I.1 Scope"])

    def test_clean_path_keeps_order(self):
        self.assertEqual(clean_path(["A", "B", "C"], {"B": "banner"}), ["A", "C"])
        self.assertEqual(clean_path(["B"], {"B": "banner"}), [])


class MapChildrenTests(unittest.TestCase):
    CHUNKS = [corpus_chunk("Top block.", section="Report Banner", section_path=["Report Banner"]),
              corpus_chunk("Body one.", section="Mud", section_path=["Mud"]),
              corpus_chunk("Stamp.", section="Report For 12-Aug-16", section_path=["Report For 12-Aug-16"]),
              corpus_chunk("Intro.", section="VI. Ops", section_path=["VI. Ops"]),
              corpus_chunk("Detail.", section="VI.1 Run", section_path=["VI.1 Run"]),
              corpus_chunk("No section."),
              ]

    def run_map(self, **options):
        return map_children(FID, "sample", "other", copy.deepcopy(self.CHUNKS), [], [], {}, **options)

    def test_default_output_is_unchanged_by_the_new_parameters(self):
        self.assertEqual(self.run_map(), self.run_map(dropped_sections=None, numbering=None))
        self.assertEqual(self.run_map(), self.run_map(dropped_sections={}, numbering=[]))

    def test_dropping_sections_changes_values_but_never_ids(self):
        before, parents_before = self.run_map()
        after, parents_after = self.run_map(dropped_sections={"Report Banner": "banner", "Report For 12-Aug-16": "report_date"})
        self.assertEqual([c["chunk_id"] for c in before], [c["chunk_id"] for c in after])
        self.assertEqual([p["parent_id"] for p in parents_before], [p["parent_id"] for p in parents_after])
        self.assertEqual([c["section"] for c in after], [None, "Mud", None, "VI. Ops", "VI.1 Run", None])
        for old, new in zip(before, after):
            self.assertEqual({k: v for k, v in old.items() if k not in ("section", "section_path")},
                             {k: v for k, v in new.items() if k not in ("section", "section_path")})
        parent_paths = {p["parent_id"]: p["section_path"] for p in parents_after}
        self.assertTrue(all(parent_paths[c["parent_id"]] == c["section_path"] for c in after))

    def test_numbered_hierarchy_changes_paths_only(self):
        before, _ = self.run_map()
        after, parents = self.run_map(numbering=NUMBERING)
        self.assertEqual([c["chunk_id"] for c in before], [c["chunk_id"] for c in after])
        self.assertEqual([c["section"] for c in before], [c["section"] for c in after])
        self.assertEqual(after[4]["section_path"], ["VI. Ops", "VI.1 Run"])
        self.assertEqual(after[5]["section_path"], [])
        self.assertTrue(all(c["section_path"] == [] or c["section_path"][-1] == c["section"] for c in after))
        self.assertEqual({p["parent_id"]: p["section_path"] for p in parents}[after[4]["parent_id"]], ["VI. Ops", "VI.1 Run"])


class ConfigTests(unittest.TestCase):
    def test_default_k1_configuration_has_no_section_context(self):
        self.assertNotIn("section_context", load_k1_config())
        self.assertNotIn("section_context", json.loads((ROOT / "configs/corpus/k1.json").read_text(encoding="utf-8")))

    def test_option_is_validated_and_enters_the_package_identity(self):
        enabled = dict(K1_CONFIG, section_context=OPTIONS)
        validate_k1_config(enabled)
        self.assertNotEqual(package_identity("fp", K1_CONFIG), package_identity("fp", enabled))
        hierarchy_off = dict(OPTIONS)
        del hierarchy_off["numbered_hierarchy"]
        self.assertNotEqual(package_identity("fp", enabled), package_identity("fp", dict(K1_CONFIG, section_context=hierarchy_off)))

    def test_invalid_options_are_rejected(self):
        broken = [dict(OPTIONS, furniture=dict(FURNITURE, min_pages=1)), dict(OPTIONS, furniture={}),
                  dict(OPTIONS, value_patterns=[{"kind": "x", "pattern": "("}]), dict(OPTIONS, numbered_hierarchy=[]),
                  dict(OPTIONS, numbered_hierarchy=[{"scheme": "a", "pattern": "^\\d+"}]), dict(OPTIONS, extra=1)]
        for options in broken:
            with self.assertRaises(ValueError, msg=str(options)[:80]):
                validate_section_context(options)


class ExportTests(PackageCase):
    def test_option_on_changes_no_id_and_invents_no_section(self):
        add_sample(self.corpus, self.root, "sample-report", self.fingerprint)
        off = self.export("off")
        on = self.export("on", config=dict(K1_CONFIG, section_context=OPTIONS))
        for name in ("files", "pages", "tables", "forms", "chunks", "parents"):
            self.assertEqual((off / f"{name}.jsonl").read_bytes(), (on / f"{name}.jsonl").read_bytes(), name)
        chunks = [json.loads(line) for line in (on / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertIn("Overview", {c["section"] for c in chunks})  # blank test pages give no banner evidence


if __name__ == "__main__":
    unittest.main()
