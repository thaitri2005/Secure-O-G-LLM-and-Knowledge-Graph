"""Regression tests for the prototype validator and gold matcher (no services needed)."""
import unittest

from prototype.kgproto.ontology import casing_key, matches_gold, same_value, validate_claim

ROW = "| 1500 | 1.75 |"
TEXT = "Well AK-3 was spud on 18 August and the rig was released 5 September 2016, a total of 19 days."


def claim(**values):
    base = {"well": "AK-3", "property": "inclination", "qualifier": "actual", "value": "1.75", "unit": "deg",
            "casing_size_in": None, "depth_ft": 1500, "quote": ROW}
    return {**base, **values}


class OntologyTests(unittest.TestCase):
    def test_validator_rules(self):
        self.assertIsNone(validate_claim(claim(), ROW))
        self.assertEqual(validate_claim(claim(value=ROW), ROW), "value must be a single number")
        self.assertEqual(validate_claim(claim(depth_ft=None), ROW), "missing depth")
        self.assertEqual(validate_claim(claim(quote="| 1500 | 2 |"), ROW), "quote not found verbatim in chunk")
        self.assertEqual(validate_claim(claim(value="2"), ROW), "value not in quote")

    def test_dates_need_their_year_in_the_passage(self):
        spud = claim(property="spud_date", unit="date", value="2016-08-18", depth_ft=None, quote="spud on 18 August")
        self.assertIsNone(validate_claim(spud, TEXT))
        self.assertEqual(validate_claim({**spud, "value": "2022-08-18"}, TEXT), "date year not in passage")

    def test_matcher_compares_dates_exactly(self):
        self.assertFalse(same_value("2022-08-26", "2016-08-18"))  # once matched within 0.5%
        self.assertTrue(same_value("1,955 feet", 1955))
        self.assertTrue(same_value("221.70000000000002", 221.7))

    def test_casing_sizes_normalize(self):
        for size in ("3-½", "3-1/2", "3 1/2", '3-1/2"'):
            self.assertEqual(casing_key(size), "3-1/2")
        fact = {"well": "AK-3", "property": "casing_depth", "qualifier": "actual", "casing_size_in": "3-1/2",
                "value": 1955}
        self.assertTrue(matches_gold(claim(property="casing_depth", unit="ft", value="1,955", casing_size_in="3-½",
                                           depth_ft=None), fact))


if __name__ == "__main__":
    unittest.main()
