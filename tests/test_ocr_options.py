"""OCR opt-in and isolation contracts without loading model dependencies."""
from pathlib import Path
import unittest

from graph_builder.ingestion.sources import load_options
from graph_builder.ingestion.runs import conversion_cache
from graph_builder.ingestion.ocr_settings import ocr_settings
from graph_builder.ingestion.ocr_metrics import score_ocr


class OcrOptionTests(unittest.TestCase):
    def test_ocr_rejects_text_layer_only_strategy(self):
        with self.assertRaisesRegex(ValueError, "text-layer-only"):
            load_options(Path("configs/ingestion/vietnamese.json"), ["chunking.strategy=pypdf"])

    def test_vietnamese_profile_and_cache_language_separation(self):
        config = Path(__file__).resolve().parents[1] / "configs/ingestion/vietnamese.json"
        options = load_options(config)
        self.assertEqual(ocr_settings(options)["languages"], ["vi", "en"])
        original = conversion_cache(Path("."), options)
        changed = load_options(config, ['ocr.languages=["en"]'])
        self.assertNotEqual(original, conversion_cache(Path("."), changed))
        changed = load_options(config, ['ocr.mode=full_page'])
        self.assertNotEqual(original, conversion_cache(Path("."), changed))

    def test_invalid_settings(self):
        for value in ({"languages": []}, {"languages": ["vi", "vi"]},
                      {"mode": "guess"}, {"confidence_threshold": True},
                      {"confidence_threshold": 2}, {"unexpected": True}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ocr_settings({"ocr": value})

    def test_diacritics_are_scored_and_unicode_composition_is_equivalent(self):
        import unicodedata
        text = "Tiếng Việt: nhiệt độ 35°C, độ sâu 1.955 m."
        self.assertEqual(score_ocr(text, unicodedata.normalize("NFD", text))["cer"], 0)
        self.assertGreater(score_ocr("độ sâu", "do sau")["cer"], 0)
        self.assertIsNone(score_ocr("", "unexpected")["cer"])

    def test_ocr_is_opt_in_and_has_separate_cache(self):
        config = Path(__file__).resolve().parents[1] / "configs/ingestion/default.json"
        baseline = load_options(config)
        enabled = load_options(config, ["do_ocr=true"])
        self.assertFalse(baseline["do_ocr"])
        self.assertTrue(enabled["do_ocr"])
        self.assertNotEqual(conversion_cache(Path("."), baseline), conversion_cache(Path("."), enabled))

    def test_ocr_requires_boolean(self):
        config = Path(__file__).resolve().parents[1] / "configs/ingestion/default.json"
        with self.assertRaisesRegex(ValueError, "boolean"):
            load_options(config, ['do_ocr="true"'])
