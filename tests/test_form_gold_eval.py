"""A-435: the label-value gold scorer must detect wrong labels, forced ambiguous pairs, filled blanks and dropped units (sensitivity of the measurement)."""
from pathlib import Path
import importlib.util
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("form_gold_eval", ROOT / "scripts" / "form_gold_eval.py")
ev = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ev)


def gold(identifier, label, y, status, value, vx=None, category="number"):
    return {"id": identifier, "pdf": "x.pdf", "page": 1, "label": label, "label_bbox": [10, y, 60, y + 8], "status": status, "expected_value": value,
            "value_bbox": [vx, y, vx + 20, y + 8] if vx is not None else None, "category": category}


def field(y, value, vx=None, vy=None):
    vy = y if vy is None else vy       # vy: where the value box really stands (a value taken from another row)
    return {"key": "k", "value": value, "key_bbox": [10, y, 60, y + 8], "value_bbox": [vx, vy, vx + 20, vy + 8] if vx is not None else None}


PAIRS = [gold("a", "Days On Location:", 100, "PAIR", "1", 200, "wrong_label_trap"), gold("b", "Proposed TD:", 120, "PAIR", "1700", 200),
         gold("c", "Last BOP Test:", 140, "BLANK", ""), gold("d", "Last Casing:", 160, "PAIR", "3.500 at 1,955", 200, "number_unit"),
         gold("e", "Pers/Hrs:", 180, "AMBIGUOUS", ""), gold("f", "Missing:", 200, "PAIR", "7", 200)]


class ScorerTests(unittest.TestCase):
    def outcomes(self, fields):
        by_page = {("x.pdf", 1): {"fields": fields}}
        return {row["id"]: row["outcome"] for row in ev.evaluate(PAIRS, lambda pdf, page: by_page[(pdf.name, page)])["rows"]}

    def test_correct_extraction(self) -> None:
        got = self.outcomes([field(100, "1", 200), field(120, "1,700".replace(",", ""), 200), field(140, ""), field(160, "3.500 at 1,955", 200)])
        self.assertEqual(got, {"a": "CORRECT", "b": "CORRECT", "c": "BLANK_OK", "d": "CORRECT", "e": "NOT_FORCED", "f": "ABSENT"})

    def test_wrong_label_is_the_value_of_another_pair(self) -> None:
        got = self.outcomes([field(100, "1700", 200, vy=120), field(140, "1", 200, vy=100), field(160, "3.500", 200)])
        self.assertEqual((got["a"], got["c"]), ("WRONG_LABEL", "WRONG_LABEL"))      # 1700 under Days On Location, '1' taken into a blank field
        self.assertEqual(got["d"], "UNIT_DROPPED")

    def test_filled_blank_forced_ambiguous_and_wrong_value(self) -> None:
        got = self.outcomes([field(100, "5", 200), field(140, "zzz", 200), field(180, "2 / 0", 200)])
        self.assertEqual((got["a"], got["c"], got["e"], got["b"]), ("WRONG_VALUE", "BLANK_FILLED", "FORCED", "ABSENT"))

    def test_summary_counts_and_denominators(self) -> None:
        by_page = {("x.pdf", 1): {"fields": [field(100, "1700", 200, vy=120)]}}
        summary = ev.evaluate(PAIRS, lambda pdf, page: by_page[(pdf.name, page)])["summary"]
        self.assertEqual((summary["pair_correct"], summary["wrong_label"], summary["blank_ok"], summary["ambiguous_forced"]), ("0/4", 1, "0/1", "0/1"))

    def test_unsupported_page_is_counted_separately(self) -> None:
        summary = ev.evaluate(PAIRS, lambda pdf, page: None)["summary"]
        self.assertEqual(summary["on_unsupported_pages"]["n"], 6)
        self.assertEqual(summary["on_supported_pages"]["n"], 0)


if __name__ == "__main__":
    unittest.main()
