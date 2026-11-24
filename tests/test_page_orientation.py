"""C-03: detect pages whose text is not upright when displayed, and optionally convert them upright (default OFF)."""
from __future__ import annotations
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

import pymupdf

from graph_builder.corpus import orientation as ori
from graph_builder.corpus.analysis import DEFAULT_ANALYSIS, analysis_config
from graph_builder.corpus.config import fingerprint, load_config
from graph_builder.corpus.qa.orientation import register_orientation
from graph_builder.corpus.qa.signals import CheckContext, Registry
from graph_builder.corpus.text_layer import source_page
ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / "data" / "interim" / "overnight" / "p1" / "c03" / "_test_orientation"
S = ori.orientation_settings({"mode": "flag"})
TEXT = ["Casing joint number 12 length 40.5 ft", "Cement job volume 25 bbl density 15.8 ppg", "Remarks: pressure test passed at 1500 psi"]


class ClassifyTests(unittest.TestCase):
    def test_verified_rotation_rolls_back_only_the_page_that_loses_a_numeric_value(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pdf"
            content = "Density 12.5 ppg, pressure -175.25 psi, casing length 47.5 ft."
            with pymupdf.open() as pdf:
                for _ in range(2):
                    page = pdf.new_page()
                    page.insert_text((32, 60), content)
                    page.set_rotation(270)
                pdf.save(source)
            digest = hashlib.sha256(source.read_bytes()).digest()
            analysis = [{"page": n, "mode": "text"} for n in (1, 2)]
            upright = ori.apply_page_orientation(source, root, analysis, ori.orientation_settings({"mode": "verify"}))

            def converted(path, page):
                if page == 1:
                    return content
                return content.replace("-175.25", "175.25") if path == upright else content.replace("47.5", "47.4")

            verified = ori.verify_working_copy(source, upright, analysis, converted)
            with pymupdf.open(verified) as pdf:
                self.assertEqual([page.rotation for page in pdf], [0, 270])
            self.assertTrue(analysis[0]["orientation"]["normalized"])
            self.assertNotIn("normalized", analysis[1]["orientation"])
            comparison = analysis[1]["orientation"]["verification"]
            self.assertEqual(comparison["original"]["numbers"], comparison["normalized"]["numbers"])
            self.assertEqual(comparison["lost_numeric_occurrences"], 1)
            self.assertEqual(comparison["decision"], "source_coverage_decreased")
            self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), digest)

    def test_verified_rotation_keeps_table_rows_in_their_columns(self):
        content = "Measured interval 130 ft, upstream pressure 25 psi, residual pressure 12 psi."
        row = ((0, "130 ft"), (1, "25 psi"))
        reordered = ((0, "25 psi"), (1, "130 ft"))
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pdf"
            with pymupdf.open() as pdf:
                for _ in range(4):
                    page = pdf.new_page()
                    page.insert_text((32, 60), content)
                    page.set_rotation(270)
                pdf.save(source)
            analysis = [{"page": n, "mode": "text"} for n in (1, 2, 3, 4)]
            upright = ori.apply_page_orientation(source, root, analysis, ori.orientation_settings({"mode": "verify"}))

            def converted(path, page):
                if path == source or page == 1:
                    return ori.RotationProbe(content, 1, Counter({row: 1}), (frozenset({"interval", "pressure"}),))
                if page == 2:
                    return ori.RotationProbe(content, 1, Counter({reordered: 1}), (frozenset({"interval", "pressure"}),))
                if page == 4:
                    return ori.RotationProbe(content, 1, Counter({row + ((2, "12 psi"),): 1}),
                                             (frozenset({"interval", "pressure", "residual"}),))
                return ori.RotationProbe(content)

            with pymupdf.open(ori.verify_working_copy(source, upright, analysis, converted)) as pdf:
                self.assertEqual([page.rotation for page in pdf], [0, 270, 270, 0])
            checks = [page["orientation"]["verification"] for page in analysis]
            self.assertEqual([check["decision"] for check in checks],
                             ["normalized", "table_evidence_decreased", "table_evidence_decreased", "normalized"])
            self.assertEqual([check["lost_numeric_table_rows"] for check in checks], [0, 1, 1, 1])
            self.assertTrue(checks[3]["improved_table_geometry"])

    def test_upright_and_compensated_rotation_are_supported(self) -> None:
        self.assertEqual(ori.classify(0, {0: 100}, S)["state"], "upright")
        compensated = ori.classify(270, {90: 100}, S)  # text stored turned, /Rotate turns it back
        self.assertEqual((compensated["state"], compensated["displayed"], compensated["status"]), ("upright", 0, "SUPPORTED"))

    def test_sideways_variants_get_the_rotate_that_makes_text_upright(self) -> None:
        for rotation, direction in ((270, 0), (90, 0), (180, 0), (0, 90), (0, 270), (0, 180), (90, 90)):
            record = ori.classify(rotation, {direction: 200}, S)
            self.assertEqual(record["state"], "sideways", (rotation, direction))
            self.assertEqual((direction + rotation) % 360, record["displayed"])
            self.assertEqual((direction + record["correction_rotate"]) % 360, 0)  # upright after the new /Rotate
            self.assertEqual((record["status"], record["reason"]), ("UNSUPPORTED_FORMAT", "rotated_page"))

    def test_mixed_oblique_and_thin_text_are_not_corrected(self) -> None:
        mixed = ori.classify(0, {0: 60, 90: 40}, S)
        self.assertEqual((mixed["state"], mixed["reason"]), ("mixed", "rotated_page"))
        self.assertNotIn("correction_rotate", mixed)
        self.assertEqual(ori.classify(0, {None: 100}, S)["state"], "mixed")
        self.assertEqual(ori.classify(0, {0: 10}, S)["state"], "no_text")
        unknown = ori.classify(90, {}, S)
        self.assertEqual((unknown["state"], unknown["status"]), ("no_text_rotated", "UNSUPPORTED_FORMAT"))
        self.assertEqual(ori.classify(0, {0: 100}, S, has_text_layer=False)["state"], "no_text")

    def test_dominant_share_threshold(self) -> None:
        self.assertEqual(ori.classify(0, {0: 79, 90: 21}, S)["state"], "mixed")
        self.assertEqual(ori.classify(0, {0: 81, 90: 19}, S)["state"], "upright")
        loose = ori.orientation_settings({"mode": "flag", "dominant_share": 0.6})
        self.assertEqual(ori.classify(0, {0: 79, 90: 21}, loose)["state"], "upright")

    def test_quarter_tolerance(self) -> None:
        self.assertEqual(ori.quarter(3, 10), 0)
        self.assertEqual(ori.quarter(-92, 10), 270)
        self.assertEqual(ori.quarter(358, 10), 0)
        self.assertIsNone(ori.quarter(45, 10))

    def test_crop_and_quarter_turn_geometry_matches_the_working_pdf(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "original.pdf"
            with pymupdf.open() as pdf:
                for rotation in (90, 180, 270):
                    page = pdf.new_page(width=380, height=560)
                    for row, value in enumerate(TEXT):
                        page.insert_text((55, 53 + row * 18), value)
                    page.draw_rect((48, 39, 280, 59))
                    page.set_cropbox(pymupdf.Rect(20, 16, 362, 530))
                    page.set_rotation(rotation)
                pdf.save(source)
            pages = [{"page": number, "rotation": rotation, "mode": "text"}
                     for number, rotation in enumerate((90, 180, 270), 1)]
            working = ori.apply_page_orientation(source, source.parent, pages, ori.orientation_settings({"mode": "normalize"}))
            for page in pages:
                number = page["page"]
                original, normalized = ori.normalized_rotation(page)
                self.assertEqual((original, normalized), (page["rotation"], 0))
                actual = source_page(source, number, displayed_origin=True, rotation_override=normalized)
                expected = source_page(working, number, displayed_origin=True)
                self.assertEqual((actual["width"], actual["height"], actual["rotation"]),
                                 (expected["width"], expected["height"], expected["rotation"]))
                self.assertEqual([word["text"] for word in actual["words"]], [word["text"] for word in expected["words"]])
                for a, b in zip(actual["words"], expected["words"]):
                    for x, y in zip(a["bbox"], b["bbox"]):
                        self.assertAlmostEqual(x, y, places=3)
                visible = source_page(source, number, displayed_origin=True)
                projected = ori.rotate_bbox(actual["rulings"][0], actual["width"], actual["height"], original)
                for a, b in zip(projected, visible["rulings"][0]):
                    self.assertAlmostEqual(a, b)


class ConfigTests(unittest.TestCase):
    def test_option_is_absent_by_default_and_fingerprint_changes_only_when_set(self) -> None:
        self.assertEqual(analysis_config({}), DEFAULT_ANALYSIS)
        self.assertNotIn("page_orientation", load_config(ROOT / "configs" / "corpus" / "default.json")["analysis"])
        base = json.loads((ROOT / "configs" / "corpus" / "default.json").read_text(encoding="utf-8-sig"))
        on = json.loads(json.dumps(base))
        on["analysis"]["page_orientation"] = {"mode": "normalize"}
        flag = json.loads(json.dumps(base))
        flag["analysis"]["page_orientation"] = {"mode": "flag"}
        prints = {fingerprint(load_config_dict(c), {}) for c in (base, on, flag)}
        self.assertEqual(len(prints), 3)
        self.assertEqual(fingerprint(load_config_dict(base), {}), fingerprint(load_config_dict(json.loads(json.dumps(base))), {}))

    def test_invalid_settings_are_rejected(self) -> None:
        for bad in ({}, {"mode": "auto"}, {"mode": "flag", "x": 1}, {"mode": "flag", "min_chars": 0}, {"mode": "flag", "dominant_share": 0.5},
                    {"mode": "flag", "angle_tolerance": 45}, {"mode": "flag", "max_steps": 10}, "normalize"):
            with self.assertRaises(ValueError, msg=str(bad)):
                analysis_config({"page_orientation": bad})
        self.assertEqual(analysis_config({"page_orientation": {"mode": "normalize"}})["page_orientation"]["mode"], "normalize")


def load_config_dict(config: dict) -> dict:
    from graph_builder.corpus.config import validate_config
    return validate_config(json.loads(json.dumps(config)))


class PdfTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            import fitz  # noqa: F401
        except ImportError:
            self.skipTest("PyMuPDF not available")
        shutil.rmtree(SCRATCH, ignore_errors=True)
        SCRATCH.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, SCRATCH, ignore_errors=True)

    def make(self, name: str, pages: list[tuple[int, int | None]]) -> Path:
        """pages = (page /Rotate, rotate argument of insert_text or None for a page without text)."""
        import fitz
        document = fitz.open()
        for rotation, text_rotate in pages:
            page = document.new_page()
            if text_rotate is not None:
                for line, text in enumerate(TEXT * 3):
                    point = {0: (72, 100 + 20 * line), 90: (120 + 20 * line, 700), 180: (500, 700 - 20 * line), 270: (500 - 20 * line, 100)}[text_rotate]
                    page.insert_text(point, text, rotate=text_rotate)
            page.set_rotation(rotation)
        path = SCRATCH / name
        document.save(str(path))
        return path

    def states(self, path: Path) -> dict[int, str]:
        return {number: record["state"] for number, record in ori.analyze_orientation(path, S).items()}

    def test_real_pdf_states_for_all_rotation_variants(self) -> None:
        # /Rotate k on upright text -> sideways; text drawn turned by k with /Rotate k -> upright again (compensated)
        for k in (90, 180, 270):
            sideways = self.make(f"sideways{k}.pdf", [(k, 0)])
            record = ori.analyze_orientation(sideways, S)[1]
            self.assertEqual((record["state"], record["displayed"], record["correction_rotate"]), ("sideways", k, 0), k)
            compensated = self.make(f"compensated{k}.pdf", [(k, k)])
            self.assertEqual(ori.analyze_orientation(compensated, S)[1]["state"], "upright", k)
        drawn_sideways = self.make("drawn.pdf", [(0, 90)])  # no /Rotate, text drawn sideways
        record = ori.analyze_orientation(drawn_sideways, S)[1]
        self.assertEqual((record["state"], record["correction_rotate"]), ("sideways", 90))

    def test_normalize_copy_makes_text_upright_and_keeps_the_original(self) -> None:
        source = self.make("mixed.pdf", [(0, 0), (270, 0), (90, 90), (0, None), (90, None)])
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        records = ori.analyze_orientation(source, S)
        self.assertEqual({n: r["state"] for n, r in records.items()},
                         {1: "upright", 2: "sideways", 3: "upright", 4: "no_text", 5: "no_text_rotated"})
        target = SCRATCH / "upright.pdf"
        self.assertEqual(ori.normalize_working_copy(source, target, records), [2])
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)  # original never modified
        after = ori.analyze_orientation(target, S)
        self.assertEqual({n: r["state"] for n, r in after.items()}, {1: "upright", 2: "upright", 3: "upright", 4: "no_text", 5: "no_text_rotated"})
        self.assertEqual([r["rotation"] for r in after.values()], [0, 0, 90, 0, 90])  # only the sideways page changed
        import fitz
        original_text = [p.get_text() for p in fitz.open(source)]
        copy_text = [p.get_text() for p in fitz.open(target)]
        self.assertEqual(original_text, copy_text)

    def test_nothing_to_correct_writes_no_file(self) -> None:
        source = self.make("fine.pdf", [(0, 0), (180, 180)])
        target = SCRATCH / "none.pdf"
        self.assertEqual(ori.normalize_working_copy(source, target, ori.analyze_orientation(source, S)), [])
        self.assertFalse(target.exists())

    def test_apply_page_orientation_modes(self) -> None:
        source = self.make("apply.pdf", [(0, 0), (270, 0), (270, None)])
        analysis = [{"page": n, "mode": "text"} for n in (1, 2, 3)]
        flag = ori.apply_page_orientation(source, SCRATCH, analysis, S)
        self.assertEqual(flag, source)
        self.assertFalse((SCRATCH / ori.UPRIGHT_COPY).exists())
        self.assertEqual([p["orientation"]["state"] for p in analysis], ["upright", "sideways", "no_text_rotated"])
        self.assertNotIn("normalized", analysis[1]["orientation"])
        normalize = ori.orientation_settings({"mode": "normalize"})
        analysis = [{"page": n, "mode": "text"} for n in (1, 2, 3)]
        converted = ori.apply_page_orientation(source, SCRATCH, analysis, normalize)
        self.assertEqual(converted, SCRATCH / ori.UPRIGHT_COPY)
        self.assertEqual((analysis[1]["orientation"]["normalized"], analysis[1]["orientation"]["applied_rotate"]), (True, 0))
        self.assertEqual(analysis[2]["orientation"]["reason"], "rotated_page")  # unknown pages stay flagged
        self.assertNotIn("normalized", analysis[0]["orientation"])

    def test_ocr_pages_are_not_judged_by_their_text_layer(self) -> None:
        source = self.make("ocr.pdf", [(270, 0), (0, 0)])
        analysis = [{"page": 1, "mode": "ocr"}, {"page": 2, "mode": "ocr"}]
        ori.apply_page_orientation(source, SCRATCH, analysis, ori.orientation_settings({"mode": "normalize"}))
        self.assertEqual([p["orientation"]["state"] for p in analysis], ["no_text_rotated", "not_assessed"])
        self.assertFalse((SCRATCH / ori.UPRIGHT_COPY).exists())

    def test_failed_copy_keeps_page_flagged_and_original_source(self) -> None:
        source = self.make("fail.pdf", [(270, 0)])
        analysis = [{"page": 1, "mode": "text"}]
        with mock.patch.object(ori, "normalize_working_copy", side_effect=OSError("disk full")):
            converted = ori.apply_page_orientation(source, SCRATCH, analysis, ori.orientation_settings({"mode": "normalize"}))
        self.assertEqual(converted, source)
        self.assertIn("OSError", analysis[0]["orientation"]["normalize_error"])
        self.assertNotIn("normalized", analysis[0]["orientation"])

    def test_unreadable_page_is_a_parsing_failure_not_a_guess(self) -> None:
        source = self.make("broken.pdf", [(0, 0)])
        with mock.patch.object(ori, "measure_steps", side_effect=RuntimeError("boom")):
            record = ori.analyze_orientation(source, S)[1]
        self.assertEqual((record["state"], record["status"], record["reason"]), ("failed", "PARSING_FAILURE", "orientation_unreadable"))

    def test_analysis_is_deterministic(self) -> None:
        source = self.make("det.pdf", [(270, 0), (0, 0)])
        self.assertEqual(ori.analyze_orientation(source, S), ori.analyze_orientation(source, S))


class QaCheckTests(unittest.TestCase):
    def signals(self, record: dict | None) -> list[str]:
        registry = register_orientation(Registry())
        context = CheckContext(registry=registry, config={}, release_dir=None, manifest={})
        entity = {"ids": {"file_id": "f", "page": 1, "page_id": "p"}, "orientation": record} if record is not None else {"ids": {"file_id": "f", "page": 1, "page_id": "p"}}
        found, _, _ = registry.run("page", context, entity, entity["ids"])
        return [f"{s['code']}:{s['severity']}" for s in found]

    def test_signals_per_state(self) -> None:
        self.assertEqual(self.signals(ori.classify(270, {0: 100}, S)), ["ROTATED_PAGE_UNNORMALIZED:WARN"])
        normalized = {**ori.classify(270, {0: 100}, S), "normalized": True, "applied_rotate": 0}
        self.assertEqual(self.signals(normalized), ["ROTATED_PAGE_NORMALIZED:INFO"])
        self.assertEqual(self.signals(ori.classify(90, {}, S)), ["ROTATED_PAGE_ORIENTATION_UNKNOWN:WARN"])
        self.assertEqual(self.signals(ori.classify(0, {0: 50, 90: 50}, S)), ["ROTATED_PAGE_MIXED:WARN"])
        self.assertEqual(self.signals({"state": "failed", "status": "PARSING_FAILURE", "reason": "orientation_unreadable"}), ["PAGE_ORIENTATION_FAILED:WARN"])

    def test_no_signal_for_upright_unassessed_or_missing_records(self) -> None:
        self.assertEqual(self.signals(ori.classify(270, {90: 100}, S)), [])  # compensated /Rotate is not a defect
        self.assertEqual(self.signals(ori.classify(0, {0: 5}, S)), [])
        self.assertEqual(self.signals({"state": "not_assessed"}), [])
        self.assertEqual(self.signals(None), [])

    def test_default_registry_is_unchanged(self) -> None:
        from graph_builder.corpus.qa.ledger import default_registry
        registry = default_registry()
        self.assertFalse([code for code in registry.reasons if code.startswith("ROTATED_PAGE")])
        self.assertNotIn("page_orientation", [check.name for check in registry.checks])


if __name__ == "__main__":
    unittest.main()
